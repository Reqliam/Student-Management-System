import threading
import time
import subprocess

from flask import Flask

from database import init_db, strftime_filter
from routes.auth import auth_bp
from routes.teacher import teacher_bp
from routes.student import student_bp
from routes.chatbot import chatbot_bp, _load_ktu

app = Flask(__name__)
app.secret_key = "secret123"

app.template_filter("strftime")(strftime_filter)

app.register_blueprint(auth_bp)
app.register_blueprint(teacher_bp)
app.register_blueprint(student_bp)
app.register_blueprint(chatbot_bp)

init_db()

# ── Background scraper ────────────────────────────────────────────────────────

def run_scraper():
    """Run scrap.py and reload the chatbot knowledge base."""
    print("[Scraper] Running scrap.py...")
    try:
        result = subprocess.run(
            ["python", "scrap.py"],
            capture_output=True, text=True, timeout=300
        )
        print("[Scraper] Done.")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print("[Scraper] Errors:", result.stderr[:500])
    except subprocess.TimeoutExpired:
        print("[Scraper] Timed out after 5 minutes.")
    except Exception as e:
        print(f"[Scraper] Failed: {e}")
    finally:
        _load_ktu()  # Reload chatbot with fresh data regardless
        print("[Scraper] Chatbot knowledge base reloaded.")


def scraper_loop():
    """Run on startup, then every 12 hours."""
    while True:
        run_scraper()
        time.sleep(12 * 60 * 60)  # 12 hours


# Start scraper in background thread (daemon so it dies with the server)
scraper_thread = threading.Thread(target=scraper_loop, daemon=True)
scraper_thread.start()

# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True)