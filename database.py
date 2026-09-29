import sqlite3
import datetime


def get_db():
    c = sqlite3.connect("attendance.db")
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = get_db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE, password TEXT, role TEXT,
            department TEXT, year TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_code TEXT, start_time REAL, teacher_id INTEGER,
            expires_at REAL, department TEXT, year TEXT
        );
        CREATE TABLE IF NOT EXISTS attendance(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER, session_id INTEGER, time_marked REAL
        );
        CREATE TABLE IF NOT EXISTS teacher_classes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER, department TEXT, year TEXT, name TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS student_scores(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER, semester_no INTEGER, score REAL,
            entered_by INTEGER, updated_at REAL,
            UNIQUE(student_id, semester_no)
        );
    """)
    c.commit()
    c.close()

    # Run migrations safely — these are no-ops if columns already exist
    migrations = [
        "ALTER TABLE sessions ADD COLUMN expires_at REAL",
        "ALTER TABLE sessions ADD COLUMN department TEXT",
        "ALTER TABLE sessions ADD COLUMN year TEXT",
        "ALTER TABLE teacher_classes ADD COLUMN name TEXT DEFAULT ''",
        "ALTER TABLE student_scores ADD COLUMN entered_by INTEGER",
        "ALTER TABLE student_scores ADD COLUMN updated_at REAL",
    ]
    for sql in migrations:
        try:
            _c = sqlite3.connect("attendance.db")
            _c.execute(sql)
            _c.commit()
            _c.close()
        except Exception:
            pass


def get_teacher_classes(tid):
    """Return list of (department, year) tuples for a teacher.
    Only reads from teacher_classes — never falls back to the users table,
    which would cause cross-teacher contamination.
    """
    db = get_db()
    rows = db.execute(
        "SELECT department, year FROM teacher_classes WHERE teacher_id=?", (tid,)
    ).fetchall()
    db.close()
    return [(r["department"], r["year"]) for r in rows]


def stu_classes_query(tc):
    ph = " OR ".join(["(department=? AND year=?)"] * len(tc))
    params = [v for d, y in tc for v in (d, y)]
    return f"SELECT id,username FROM users WHERE role='student' AND ({ph})", params


def strftime_filter(ts, fmt="%d %b"):
    return datetime.datetime.fromtimestamp(ts).strftime(fmt)