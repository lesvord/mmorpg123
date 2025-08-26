# routes_public.py
from flask import Blueprint, redirect, url_for

bp = Blueprint("public", __name__)

@bp.get("/")
def index():
    # Главная сразу ведёт в мир
    return redirect(url_for("world.page"))
