import io
import base64
import time

import qrcode
from flask import Blueprint, render_template, request, redirect, session, jsonify
from urllib.parse import urlencode

from database import get_db, get_teacher_classes, stu_classes_query
from ml_model import get_model, predict

teacher_bp = Blueprint("teacher", __name__)


@teacher_bp.route("/teacher")
def teacher_dashboard():
    if session.get("role") != "teacher":
        return redirect("/")
    db         = get_db()
    rows       = db.execute(
        "SELECT department,year,name FROM teacher_classes WHERE teacher_id=?",
        (session["user_id"],),
    ).fetchall()
    classes_data = [
        {"dept": r["department"], "year": r["year"], "name": r["name"] or ""}
        for r in rows
    ]
    classes = [(r["department"], r["year"]) for r in rows]
    model   = get_model(db)
    sd, sy  = request.args.get("dept"), request.args.get("year")
    if classes and (sd, sy) not in classes:
        sd, sy = classes[0]
    students = []
    if sd and sy:
        for stu in db.execute(
            "SELECT id,username FROM users WHERE role='student' "
            "AND department=? AND year=? ORDER BY username",
            (sd, sy),
        ).fetchall():
            sc = db.execute(
                "SELECT semester_no,score FROM student_scores "
                "WHERE student_id=? ORDER BY semester_no",
                (stu["id"],),
            ).fetchall()
            ls   = float(sc[-1]["score"]) if sc else None
            lsem = int(sc[-1]["semester_no"]) if sc else None
            students.append({
                "id":        stu["id"],
                "username":  stu["username"],
                "scores":    [
                    {"semester_no": int(r["semester_no"]), "score": float(r["score"])}
                    for r in sc
                ],
                "predicted": predict(
                    ls, lsem, model,
                    history=[float(r["score"]) for r in sc],
                ) if ls else None,
            })
    db.close()
    return render_template(
        "teacher.html",
        username=session["username"],
        classes_data=classes_data,
        classes=classes,
        selected_dept=sd or "",
        selected_year=sy or "",
        students=students,
        confidence=model.get("confidence", "Low"),
        saved=request.args.get("saved") == "1",
        error=request.args.get("error", ""),
    )


@teacher_bp.route("/update_classes", methods=["POST"])
def update_classes():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
    classes = request.get_json().get("classes", [])
    tid     = session["user_id"]
    db      = get_db()
    db.execute("DELETE FROM teacher_classes WHERE teacher_id=?", (tid,))
    for c in classes:
        if c.get("dept") and c.get("year"):
            db.execute(
                "INSERT INTO teacher_classes (teacher_id,department,year,name) "
                "VALUES (?,?,?,?)",
                (tid, c["dept"], c["year"], c.get("name", "")),
            )
    db.commit()
    db.close()
    return jsonify({"ok": True})


@teacher_bp.route("/generate_qr")
def generate_qr():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
    now  = time.time()
    code = str(int(now))
    dept = request.args.get("dept", "")
    year = request.args.get("year", "")
    db   = get_db()
    db.execute(
        "INSERT INTO sessions (session_code,start_time,teacher_id,expires_at,department,year) "
        "VALUES (?,?,?,?,?,?)",
        (code, now, session["user_id"], now + 120, dept, year),
    )
    db.commit()
    db.close()
    buf = io.BytesIO()
    qrcode.make(code).save(buf, format="PNG")
    return jsonify({
        "code":       code,
        "expires_at": now + 300,
        "dept":       dept,
        "year":       year,
        "qr_b64":     base64.b64encode(buf.getvalue()).decode(),
    })


@teacher_bp.route("/save_score", methods=["POST"])
def save_score():
    role = session.get("role")
    if role not in ("teacher", "student"):
        return redirect("/")
    base = "/teacher" if role == "teacher" else "/student"
    try:
        sem   = int(request.form["semester_no"])
        score = float(request.form["score"])
    except Exception:
        return redirect(base + "?" + urlencode({"error": "Invalid input."}))
    if not (1 <= sem <= 12 and 0 <= score <= 10):
        return redirect(
            base + "?" + urlencode({"error": "Semester 1-12 and SGPA 0-10 required."})
        )
    db     = get_db()
    actor  = session["user_id"]
    target = actor
    rp     = {"saved": "1"}
    if role == "teacher":
        try:
            target = int(request.form["student_id"])
        except Exception:
            db.close()
            return redirect(base + "?" + urlencode({"error": "Select a valid student."}))
        stu = db.execute(
            "SELECT id,department,year FROM users WHERE id=? AND role='student'",
            (target,),
        ).fetchone()
        if not stu or (stu["department"], stu["year"]) not in set(
            get_teacher_classes(actor)
        ):
            db.close()
            return redirect(
                base + "?" + urlencode({"error": "Student not found or not in your class."})
            )
        rp.update({"dept": stu["department"], "year": stu["year"]})
    db.execute(
        """INSERT INTO student_scores
               (student_id, semester_no, score, entered_by, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(student_id, semester_no) DO UPDATE
           SET score=excluded.score,
               entered_by=excluded.entered_by,
               updated_at=excluded.updated_at""",
        (target, sem, score, actor, time.time()),
    )
    db.commit()
    db.close()
    return redirect(base + "?" + urlencode(rp))


@teacher_bp.route("/class_attendance")
def class_attendance():
    if session.get("role") != "teacher":
        return redirect("/")
    tid        = session["user_id"]
    tc         = get_teacher_classes(tid)
    dept, year = request.args.get("dept", ""), request.args.get("year", "")
    db         = get_db()
    if not tc:
        db.close()
        return render_template(
            "class_attendance.html", records=[], total_sessions=0, dept="", year=""
        )
    if dept and year:
        students = db.execute(
            "SELECT id,username FROM users WHERE role='student' AND department=? AND year=?",
            (dept, year),
        ).fetchall()
    else:
        q, p     = stu_classes_query(tc)
        students = db.execute(q, p).fetchall()
    total   = db.execute(
        "SELECT COUNT(*) FROM sessions WHERE teacher_id=? AND department=? AND year=?",
        (tid, dept or (tc[0][0] if tc else ""), year or (tc[0][1] if tc else "")),
    ).fetchone()[0]
    records = [
        {
            "username": s["username"],
            "present":  db.execute(
                "SELECT COUNT(*) FROM attendance a "
                "JOIN sessions s ON s.id=a.session_id "
                "WHERE a.student_id=? AND s.teacher_id=? "
                "AND s.department=? AND s.year=?",
                (s["id"], tid, dept or (tc[0][0] if tc else ""), year or (tc[0][1] if tc else "")),
            ).fetchone()[0],
        }
        for s in students
    ]
    db.close()
    return render_template(
        "class_attendance.html",
        records=records, total_sessions=total, dept=dept, year=year,
    )


@teacher_bp.route("/edit_attendance", methods=["GET"])
def edit_attendance():
    if session.get("role") != "teacher":
        return redirect("/")
    tid        = session["user_id"]
    tc         = get_teacher_classes(tid)
    dept, year = request.args.get("dept", ""), request.args.get("year", "")
    db         = get_db()
    sessions_list = db.execute(
        "SELECT id,session_code,start_time FROM sessions "
        "WHERE teacher_id=? ORDER BY start_time DESC",
        (tid,),
    ).fetchall()
    if dept and year:
        students = db.execute(
            "SELECT id,username FROM users WHERE role='student' AND department=? AND year=?",
            (dept, year),
        ).fetchall()
    elif tc:
        q, p     = stu_classes_query(tc)
        students = db.execute(q, p).fetchall()
    else:
        students = []
    matrix = {}
    for m in db.execute(
        "SELECT student_id,session_id FROM attendance"
    ).fetchall():
        matrix.setdefault(m["student_id"], set()).add(m["session_id"])
    db.close()
    return render_template(
        "edit_attendance.html",
        sessions_list=sessions_list,
        students=students,
        matrix=matrix,
        dept=dept,
        year=year,
    )


@teacher_bp.route("/edit_attendance", methods=["POST"])
def edit_attendance_save():
    if session.get("role") != "teacher":
        return jsonify({"error": "Unauthorized"}), 403
    db = get_db()
    for c in request.get_json().get("changes", []):
        sid, ses_id, present = c["student_id"], c["session_id"], c["present"]
        exists = db.execute(
            "SELECT id FROM attendance WHERE student_id=? AND session_id=?",
            (sid, ses_id),
        ).fetchone()
        if present and not exists:
            db.execute(
                "INSERT INTO attendance (student_id,session_id,time_marked) VALUES (?,?,?)",
                (sid, ses_id, time.time()),
            )
        elif not present and exists:
            db.execute(
                "DELETE FROM attendance WHERE student_id=? AND session_id=?",
                (sid, ses_id),
            )
    db.commit()
    db.close()
    return jsonify({"ok": True})