from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import os

bp = Blueprint("admin", __name__, url_prefix="/admin")

ADMIN_PASSWORD = "les"

@bp.before_request
def check_login():
    if request.endpoint != "admin.login" and not session.get("logged_in"):
        return redirect(url_for("admin.login"))

@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["logged_in"] = True
            return redirect(url_for("admin.map_view"))
    return render_template("admin_login.html")

@bp.route("/")
def map_view():
    return render_template("admin_map.html")

@bp.route("/tile_info")
def tile_info():
    x = int(request.args.get("x"))
    y = int(request.args.get("y"))
    # Здесь берём данные из твоей игры
    data = {
        "biome": "forest",
        "weather": "sunny",
        "coords": (x, y)
    }
    return jsonify(data)

@bp.route("/set_tile", methods=["POST"])
def set_tile():
    x = int(request.form.get("x"))
    y = int(request.form.get("y"))
    biome = request.form.get("biome")
    weather = request.form.get("weather")
    # Здесь вносим изменения в карту
    return jsonify({"status": "ok"})
