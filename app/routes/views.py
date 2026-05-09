"""
HTML page routes — serve Jinja2 templates.
All authentication is enforced client-side via JWT stored in localStorage.
"""

from flask import Blueprint, redirect, render_template, url_for

views_bp = Blueprint("views", __name__)


@views_bp.get("/")
def index():
    return redirect(url_for("views.search"))


@views_bp.get("/login")
def login():
    return render_template("auth.html")


@views_bp.get("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@views_bp.get("/search")
def search():
    return render_template("search.html")


@views_bp.get("/results")
def results():
    return render_template("results.html")


@views_bp.get("/admin")
def admin():
    return render_template("admin.html")
