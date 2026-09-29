import json
import os
import time

from flask import Blueprint, request, jsonify, session
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from database import get_db

chatbot_bp = Blueprint("chatbot", __name__)

# ── Load KTU knowledge base ───────────────────────────────────────────────────

JSON_FILE = "ktu.json"
_questions = []
_answers   = []
_vectorizer = None
_question_vectors = None

def _load_ktu():
    global _questions, _answers, _vectorizer, _question_vectors
    if not os.path.isfile(JSON_FILE):
        return
    with open(JSON_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    _questions = []
    _answers   = []
    for intent in data.get("intents", []):
        responses = intent.get("responses", [])
        answer = responses[0] if responses else "I don't have information on that."
        for pattern in intent.get("patterns", []):
            if pattern.strip():
                _questions.append(pattern.strip())
                _answers.append(answer)
    if _questions:
        _vectorizer = TfidfVectorizer()
        _question_vectors = _vectorizer.fit_transform(_questions)

_load_ktu()


# ── Live data helpers ─────────────────────────────────────────────────────────

def _get_student_attendance(sid):
    """Returns (present, total, percentage) for a student."""
    db = get_db()
    user = db.execute("SELECT department, year FROM users WHERE id=?", (sid,)).fetchone()
    if not user:
        db.close()
        return None
    sdept, syear = user["department"], user["year"]
    total = db.execute(
        """SELECT COUNT(DISTINCT sessions.id) FROM sessions
           WHERE (sessions.department=? AND sessions.year=?)
           OR (sessions.department IS NULL AND sessions.year IS NULL
               AND EXISTS (SELECT 1 FROM teacher_classes
                           WHERE teacher_classes.teacher_id=sessions.teacher_id
                           AND teacher_classes.department=? AND teacher_classes.year=?))""",
        (sdept, syear, sdept, syear),
    ).fetchone()[0]
    present = db.execute(
        "SELECT COUNT(*) FROM attendance WHERE student_id=?", (sid,)
    ).fetchone()[0]
    db.close()
    pct = round(present / total * 100, 1) if total > 0 else 0
    return present, total, pct


def _get_student_scores(sid):
    """Returns list of {semester_no, score} dicts."""
    db = get_db()
    rows = db.execute(
        "SELECT semester_no, score FROM student_scores WHERE student_id=? ORDER BY semester_no",
        (sid,),
    ).fetchall()
    db.close()
    return [{"semester_no": r["semester_no"], "score": float(r["score"])} for r in rows]


def _get_class_attendance_summary(tid):
    """For a teacher: returns list of {dept, year, total_sessions, students, avg_attendance}."""
    from database import get_teacher_classes
    db     = get_db()
    tc     = get_teacher_classes(tid)
    result = []
    for dept, year in tc:
        total = db.execute(
            "SELECT COUNT(*) FROM sessions WHERE teacher_id=? AND department=? AND year=?",
            (tid, dept, year),
        ).fetchone()[0]
        students = db.execute(
            "SELECT COUNT(*) FROM users WHERE role='student' AND department=? AND year=?",
            (dept, year),
        ).fetchone()[0]
        result.append({"dept": dept, "year": year, "total_sessions": total, "students": students})
    db.close()
    return result


# ── Intent detection for live queries ────────────────────────────────────────

ATTENDANCE_KEYWORDS = {"attendance", "present", "absent", "sessions", "percentage", "classes"}
SGPA_KEYWORDS       = {"sgpa", "cgpa", "score", "marks", "semester", "gpa", "grade", "predict"}
CLASS_KEYWORDS      = {"class", "students", "my class", "department", "how many students"}

def _is_live_query(text):
    t = text.lower()
    if any(k in t for k in ATTENDANCE_KEYWORDS):
        return "attendance"
    if any(k in t for k in SGPA_KEYWORDS):
        return "sgpa"
    if any(k in t for k in CLASS_KEYWORDS):
        return "class"
    return None


def _answer_live_student(query_type, sid, username):
    if query_type == "attendance":
        result = _get_student_attendance(sid)
        if not result:
            return "I couldn't find your attendance data. Make sure your class is assigned."
        present, total, pct = result
        status = "✅ You're safe!" if pct >= 75 else "⚠️ Your attendance is below 75%. Please attend more classes."
        return (
            f"📊 **Attendance for {username}**\n"
            f"• Present: {present} / {total} sessions\n"
            f"• Percentage: {pct}%\n"
            f"{status}"
        )
    if query_type == "sgpa":
        scores = _get_student_scores(sid)
        if not scores:
            return "No SGPA records found yet. Add your semester scores from the dashboard."
        lines = [f"• Semester {r['semester_no']}: {r['score']}" for r in scores]
        avg = round(sum(r["score"] for r in scores) / len(scores), 2)
        return (
            f"📈 **Your SGPA Records**\n"
            + "\n".join(lines)
            + f"\n• Average SGPA: {avg}"
        )
    return None


def _answer_live_teacher(query_type, tid):
    if query_type in ("attendance", "class"):
        summary = _get_class_attendance_summary(tid)
        if not summary:
            return "You have no classes assigned yet. Use 'Manage My Classes' to set them up."
        lines = [
            f"• {s['dept']} Year {s['year']}: {s['total_sessions']} sessions, {s['students']} students"
            for s in summary
        ]
        return "📋 **Your Classes Summary**\n" + "\n".join(lines)
    return None


# ── Main chat endpoint ────────────────────────────────────────────────────────

@chatbot_bp.route("/chat", methods=["POST"])
def chat():
    if not session.get("role"):
        return jsonify({"error": "Not logged in"}), 401

    data       = request.get_json()
    user_input = (data.get("message") or "").strip()
    if not user_input:
        return jsonify({"reply": "Please type something!"})

    role = session["role"]
    uid  = session["user_id"]
    name = session["username"]

    # 1.live data first
    query_type = _is_live_query(user_input)
    if query_type:
        if role == "student":
            live_reply = _answer_live_student(query_type, uid, name)
        else:
            live_reply = _answer_live_teacher(query_type, uid)
        if live_reply:
            return jsonify({"reply": live_reply})

    # 2. Fall back to KTU knowledge base
    if _vectorizer is None or not _questions:
        return jsonify({"reply": "KTU knowledge base is not loaded. Please ensure ktu.json exists."})

    user_vec   = _vectorizer.transform([user_input])
    similarity = cosine_similarity(user_vec, _question_vectors)
    best_idx   = similarity.argmax()
    confidence = similarity[0][best_idx]

    if confidence < 0.2:
        return jsonify({"reply": "I'm not sure about that. Try asking about attendance, SGPA, KTU rules, or notices."})

    return jsonify({"reply": _answers[best_idx]})


# ── Reload endpoint (call after scraper runs) ─────────────────────────────────

@chatbot_bp.route("/reload_ktu", methods=["POST"])
def reload_ktu():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
    _load_ktu()
    return jsonify({"ok": True, "loaded": len(_questions)})