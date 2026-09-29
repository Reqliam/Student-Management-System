from flask import Blueprint, render_template, request, redirect, session
from database import get_db

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db   = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (request.form["username"], request.form["password"]),
        ).fetchone()
        db.close()
        if user:
            for k in ("id", "username", "role", "department", "year"):
                session["user_id" if k == "id" else k] = user[k]
            return redirect("/teacher" if user["role"] == "teacher" else "/student")
        return render_template("login.html", error="Invalid username or password")
    return render_template("login.html")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u, p, role = (
            request.form["username"],
            request.form["password"],
            request.form["role"],
        )
        db = get_db()
        if db.execute("SELECT id FROM users WHERE username=?", (u,)).fetchone():
            db.close()
            return render_template("register.html", error="Username already exists!")
        dept = year = ""
        if role != "teacher":
            dept = request.form.get("department", "").strip()
            year = request.form.get("year", "").strip()
            if not dept or not year:
                db.close()
                return render_template(
                    "register.html",
                    error="Please select your department and year.",
                )
        db.execute(
            "INSERT INTO users (username,password,role,department,year) VALUES (?,?,?,?,?)",
            (u, p, role, dept, year),
        )
        db.commit()
        db.close()
        return redirect("/")
    return render_template("register.html")


@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")