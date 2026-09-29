import os
import time
import json
import re
import PyPDF2
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


URL = "https://ktu.edu.in/menu/announcements"
DOWNLOAD_FOLDER = os.path.abspath("latest_download")
JSON_FILE = os.path.abspath("ktu.json")

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ─────────────────────────────────────────────
# LOAD EXISTING ktu.json
# ─────────────────────────────────────────────
if os.path.isfile(JSON_FILE):
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        ktu_data = json.load(f)
else:
    # Create fresh structure if file doesn't exist
    ktu_data = {"intents": []}

# Build a set of existing tags for duplicate detection
existing_tags = {intent["tag"] for intent in ktu_data.get("intents", [])}

# Also track existing patterns to avoid duplicate headings
existing_patterns = set()
for intent in ktu_data.get("intents", []):
    for p in intent.get("patterns", []):
        existing_patterns.add(p.strip().lower())

# ─────────────────────────────────────────────
# CHROME SETUP
# ─────────────────────────────────────────────
chrome_options = Options()
prefs = {
    "download.default_directory": DOWNLOAD_FOLDER,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "plugins.always_open_pdf_externally": True
}
chrome_options.add_experimental_option("prefs", prefs)
chrome_options.add_argument("--start-maximized")

driver = webdriver.Chrome(
    service=Service(ChromeDriverManager().install()),
    options=chrome_options
)

driver.get(URL)
wait = WebDriverWait(driver, 25)

new_intents = []  # Collect all new intents to add

# ─────────────────────────────────────────────
# HELPER: Convert heading to a clean JSON tag
# ─────────────────────────────────────────────
def heading_to_tag(heading):
    tag = heading.lower()
    tag = re.sub(r"[^a-z0-9]+", "_", tag)   # replace non-alphanumeric with _
    tag = tag.strip("_")[:60]                 # trim underscores and cap length
    return f"ktu_{tag}"


# ─────────────────────────────────────────────
# HELPER: Generate natural question patterns from a notice heading
# ─────────────────────────────────────────────
def generate_patterns(heading):
    return [
        heading,
        f"What is {heading}",
        f"Tell me about {heading}",
        f"Details of {heading}",
        f"Explain {heading}",
    ]


# ─────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────
def clean_pdf_text(text):
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        line = " ".join(line.split())
        if line:
            cleaned.append(line)
    return " ".join(cleaned)


# ─────────────────────────────────────────────
# SCRAPING — All visible notices
# ─────────────────────────────────────────────
try:
    wait.until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "div.p-t-15.p-b-15.shadow")
        )
    )
    time.sleep(2)

    notices = driver.find_elements(By.CSS_SELECTOR, "div.p-t-15.p-b-15.shadow")
    print(f"Found {len(notices)} notices on the page.")

    for i, notice in enumerate(notices):
        # ── Get heading ──
        try:
            heading = notice.find_element(By.TAG_NAME, "h6").text.strip()
        except Exception:
            print(f"Notice {i+1}: No heading found — skipping.")
            continue

        # ── Duplicate check (by pattern match) ──
        if heading.strip().lower() in existing_patterns:
            print(f"Notice {i+1}: Already in ktu.json — skipping.")
            continue

        tag = heading_to_tag(heading)

        # Ensure tag is unique (append number if collision)
        base_tag = tag
        counter = 1
        while tag in existing_tags:
            tag = f"{base_tag}_{counter}"
            counter += 1
        existing_tags.add(tag)

        print(f"Notice {i+1}: New — '{heading[:60]}...'")

        # ── Try to download PDF ──
        pdf_text = ""
        try:
            download_button = notice.find_element(By.TAG_NAME, "button")
            existing_files = set(os.listdir(DOWNLOAD_FOLDER))
            driver.execute_script("arguments[0].click();", download_button)
            time.sleep(10)

            new_files = set(os.listdir(DOWNLOAD_FOLDER)) - existing_files

            if new_files:
                pdf_path = os.path.join(DOWNLOAD_FOLDER, new_files.pop())
                print(f"  Downloaded: {os.path.basename(pdf_path)}")

                with open(pdf_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text = page.extract_text()
                        if text:
                            pdf_text += text + "\n"
                pdf_text = clean_pdf_text(pdf_text)
            else:
                print(f"  No PDF downloaded — using heading as response.")
                pdf_text = f"Notice: {heading}"

        except Exception as e:
            print(f"  No download button or error: {e}")
            pdf_text = f"Notice: {heading}"

        # ── Build intent and add to list ──
        new_intent = {
            "tag": tag,
            "patterns": generate_patterns(heading),
            "responses": [pdf_text if pdf_text else f"No details available for: {heading}"]
        }

        new_intents.append(new_intent)
        existing_patterns.add(heading.strip().lower())

finally:
    driver.quit()

# ─────────────────────────────────────────────
# SAVE back to ktu.json
# ─────────────────────────────────────────────
if not new_intents:
    print("\nNo new notices found. ktu.json is already up to date.")
else:
    ktu_data["intents"].extend(new_intents)

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(ktu_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Added {len(new_intents)} new notice(s) to {JSON_FILE}")
    for intent in new_intents:
        print(f"   • [{intent['tag']}] {intent['patterns'][0][:70]}")