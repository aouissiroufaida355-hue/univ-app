import os, hmac, secrets, time
from functools import wraps
import psycopg2, psycopg2.extras
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, abort)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")
DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")


def db():
    return psycopg2.connect(DATABASE_URL,
                            cursor_factory=psycopg2.extras.RealDictCursor)


def query(sql, args=(), one=False):
    conn = db()
    try:
        with conn, conn.cursor() as cur:   # commit automatique
            cur.execute(sql, args)
            if cur.description:
                rows = cur.fetchall()
                return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def init_db():
    for _ in range(30):                    # attend que PostgreSQL soit prêt
        try:
            conn = db()
            break
        except psycopg2.OperationalError:
            time.sleep(2)
    else:
        raise RuntimeError("Database unreachable")
    with conn, conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(42)")  # évite la course entre workers
        cur.execute("""
            CREATE TABLE IF NOT EXISTS departments (
              id SERIAL PRIMARY KEY,
              name VARCHAR(120) NOT NULL,
              description TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS announcements (
              id SERIAL PRIMARY KEY,
              title VARCHAR(200) NOT NULL,
              content TEXT NOT NULL,
              created_at TIMESTAMP NOT NULL DEFAULT NOW());""")
        cur.execute("SELECT COUNT(*) AS n FROM departments")
        if cur.fetchone()["n"] == 0:
            cur.executemany(
                "INSERT INTO departments(name, description) VALUES (%s,%s)", [
                ("Computer Science", "Software engineering, AI, networks and cloud computing."),
                ("Electrical Engineering", "Power systems, electronics and automation."),
                ("Mathematics", "Pure and applied mathematics, statistics and data analysis."),
                ("Business Administration", "Management, accounting and entrepreneurship."),
            ])
            cur.executemany(
                "INSERT INTO announcements(title, content) VALUES (%s,%s)", [
                ("Welcome to Atlas University", "Registration for the new semester is now open."),
                ("Library opening hours", "The library is open from 8:00 to 20:00, Sunday to Thursday."),
                ("Cloud Computing project", "Groups must submit their project before December 4."),
            ])
    conn.close()


init_db()


# ---------- sécurité ----------
def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def check_csrf():
    if request.method == "POST":
        if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "x")):
            abort(400, "Invalid CSRF token")


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrapper


# ---------- pages publiques ----------
@app.route("/")
def home():
    recent = query("SELECT * FROM announcements ORDER BY created_at DESC LIMIT 3")
    return render_template("index.html", announcements=recent)


@app.route("/departments")
def departments():
    return render_template("departments.html",
                           departments=query("SELECT * FROM departments ORDER BY name"))


@app.route("/news")
def news():
    return render_template("news.html",
                           announcements=query("SELECT * FROM announcements ORDER BY created_at DESC"))


@app.route("/health")
def health():
    query("SELECT 1")
    return "ok"


# ---------- administration ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, p = request.form.get("username", ""), request.form.get("password", "")
        if hmac.compare_digest(u, ADMIN_USER) and hmac.compare_digest(p, ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Invalid credentials")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/admin")
@admin_required
def admin():
    return render_template("admin.html",
                           announcements=query("SELECT * FROM announcements ORDER BY created_at DESC"))


@app.route("/admin/new", methods=["GET", "POST"])
@admin_required
def add():
    if request.method == "POST":
        query("INSERT INTO announcements(title, content) VALUES (%s,%s)",
              (request.form["title"].strip(), request.form["content"].strip()))
        flash("Announcement added")
        return redirect(url_for("admin"))
    return render_template("form.html", a=None)


@app.route("/admin/edit/<int:aid>", methods=["GET", "POST"])
@admin_required
def edit(aid):
    a = query("SELECT * FROM announcements WHERE id=%s", (aid,), one=True)
    if not a:
        abort(404)
    if request.method == "POST":
        query("UPDATE announcements SET title=%s, content=%s WHERE id=%s",
              (request.form["title"].strip(), request.form["content"].strip(), aid))
        flash("Announcement updated")
        return redirect(url_for("admin"))
    return render_template("form.html", a=a)


@app.route("/admin/delete/<int:aid>", methods=["POST"])
@admin_required
def delete(aid):
    query("DELETE FROM announcements WHERE id=%s", (aid,))
    flash("Announcement deleted")
    return redirect(url_for("admin"))
