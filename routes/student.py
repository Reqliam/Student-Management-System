import time

from flask import Blueprint, render_template, request, redirect, session
from urllib.parse import urlencode

from database import get_db, get_teacher_classes
from ml_model import get_model, predict, clamp

student_bp = Blueprint("student", __name__)


# ── Context builder ───────────────────────────────────────────────────────────

def student_ctx(db, sid, username, saved=False, error=""):
    model = get_model(db)
    recs  = [
        dict(r) for r in db.execute(
            "SELECT semester_no,score FROM student_scores "
            "WHERE student_id=? ORDER BY semester_no",
            (sid,),
        ).fetchall()
    ]
    ls    = float(recs[-1]["score"])       if recs else None
    lsem  = int(recs[-1]["semester_no"])   if recs else None
    hist  = [float(r["score"]) for r in recs]
    pred  = predict(ls, lsem, model, history=hist) if ls is not None else None
    if pred is None:
        rec = "Add your latest semester SGPA to get a prediction."
    elif pred >= 8.5:
        rec = "Maintain your current study rhythm and target advanced practice problems."
    elif pred >= 7.0:
        rec = "Focus on weak subjects and keep a steady revision schedule."
    else:
        rec = "Build a weekly improvement plan and meet your mentor for targeted support."
    return {
        "username":       username,
        "records":        recs,
        "latest_score":   ls,
        "next_semester":  (lsem + 1 if lsem else 1),
        "predicted":      pred,
        "confidence":     model.get("confidence", "Low"),
        "recommendation": rec,
        "saved":          saved,
        "error":          error,
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@student_bp.route("/student")
def student_dashboard():
    if session.get("role") != "student":
        return redirect("/")
    db  = get_db()
    ctx = student_ctx(
        db, session["user_id"], session["username"],
        saved=request.args.get("saved") == "1",
        error=request.args.get("error", ""),
    )
    db.close()
    return render_template("student.html", **ctx)


@student_bp.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    if session.get("role") != "student":
        return redirect("/")
    sid, sdept, syear = (
        session["user_id"],
        session["department"],
        session["year"],
    )
    db = get_db()

    def err(msg):
        ctx = student_ctx(db, sid, session["username"], error=msg)
        db.close()
        return render_template("student.html", **ctx)

    if not sdept or not syear:
        return err("Your account has no class assigned. Contact admin.")
    sess = db.execute(
        "SELECT * FROM sessions WHERE session_code=?",
        (request.form["session_code"].strip(),),
    ).fetchone()
    if not sess:
        return err("Invalid session code.")
    if sess["expires_at"] and time.time() > sess["expires_at"]:
        return err("QR expired. Ask teacher to generate a new one.")
    if not any(
        d == sdept and y == syear
        for d, y in get_teacher_classes(sess["teacher_id"])
    ):
        return err("This session does not belong to your class.")
    if db.execute(
        "SELECT id FROM attendance WHERE student_id=? AND session_id=?",
        (sid, sess["id"]),
    ).fetchone():
        return err("Already marked attendance for this session.")
    db.execute(
        "INSERT INTO attendance (student_id,session_id,time_marked) VALUES (?,?,?)",
        (sid, sess["id"], time.time()),
    )
    db.commit()
    ctx = student_ctx(db, sid, session["username"])
    ctx["success"] = "Attendance marked successfully!"
    db.close()
    return render_template("student.html", **ctx)


@student_bp.route("/my_attendance")
def my_attendance():
    if session.get("role") != "student":
        return redirect("/")
    sid, sdept, syear = (
        session["user_id"],
        session["department"],
        session["year"],
    )
    db    = get_db()
    total = db.execute(
        """SELECT COUNT(DISTINCT sessions.id) FROM sessions
           WHERE (sessions.department=? AND sessions.year=?)
           OR (
               sessions.department IS NULL AND sessions.year IS NULL
               AND EXISTS (
                   SELECT 1 FROM teacher_classes
                   WHERE teacher_classes.teacher_id = sessions.teacher_id
                   AND teacher_classes.department = ? AND teacher_classes.year = ?
               )
           )
           OR (
               sessions.department IS NULL AND sessions.year IS NULL
               AND EXISTS (
                   SELECT 1 FROM users
                   WHERE users.id = sessions.teacher_id
                   AND users.department = ? AND users.year = ?
                   AND NOT EXISTS (
                       SELECT 1 FROM teacher_classes
                       WHERE teacher_classes.teacher_id = sessions.teacher_id
                   )
               )
           )""",
        (sdept, syear, sdept, syear, sdept, syear),
    ).fetchone()[0]
    present = db.execute(
        "SELECT COUNT(*) FROM attendance WHERE student_id=?", (sid,)
    ).fetchone()[0]
    db.close()
    return render_template(
        "student_attendance.html",
        total_present=present,
        total_sessions=total,
        percentage=round(present / total * 100, 2) if total > 0 else 0,
    )


@student_bp.route("/save_score", methods=["POST"])
def save_score_student():
    """Student-only save_score (teachers go through teacher_bp.save_score)."""
    if session.get("role") != "student":
        return redirect("/")
    try:
        sem   = int(request.form["semester_no"])
        score = float(request.form["score"])
    except Exception:
        return redirect("/student?" + urlencode({"error": "Invalid input."}))
    if not (1 <= sem <= 12 and 0 <= score <= 10):
        return redirect(
            "/student?" + urlencode({"error": "Semester 1-12 and SGPA 0-10 required."})
        )
    db     = get_db()
    actor  = session["user_id"]
    db.execute(
        """INSERT INTO student_scores
               (student_id, semester_no, score, entered_by, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(student_id, semester_no) DO UPDATE
           SET score=excluded.score,
               entered_by=excluded.entered_by,
               updated_at=excluded.updated_at""",
        (actor, sem, score, actor, time.time()),
    )
    db.commit()
    db.close()
    return redirect("/student?" + urlencode({"saved": "1"}))


@student_bp.route("/mark_entry")
@student_bp.route("/performance")
def student_redirects():
    return redirect("/student") if session.get("role") == "student" else redirect("/")