import os, time
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, current_app
from helpers import current_user
from services_world import (
    ensure_world_models,
    get_world_state, set_destination, stop_hero, set_speed, build_here,
    rest_here, wake_up, camp_start, camp_leave, get_patch_view
)
from gathering_tables import serialize_modes, DEFAULT_MODE_KEY

bp = Blueprint("world", __name__, url_prefix="/world")  # <-- ВАЖНО: __name__


def _scan_tile_versions():
    root = os.path.join(current_app.static_folder, "tiles")
    versions = {}
    try:
        for fn in os.listdir(root):
            low = fn.lower()
            if not low.endswith((".webp", ".avif", ".png", ".jpg", ".jpeg")):
                continue
            full = os.path.join(root, fn)
            try:
                versions[fn] = int(os.path.getmtime(full))
            except Exception:
                versions[fn] = int(time.time())
    except Exception:
        pass
    return versions


@bp.get("/")
def page():
    u = current_user()
    if not u:
        # если не авторизован — на лендинг аккаунтов/публичную
        return redirect(url_for("accounts.landing") if "accounts.landing" in current_app.view_functions else url_for("public.index"))
    ensure_world_models()
    return render_template(
        "world.html",
        tile_versions=_scan_tile_versions(),
        state_get_url=url_for("world.api_state_get"),
        gather_modes=serialize_modes(),
        gather_default_mode=DEFAULT_MODE_KEY,
    )


@bp.get("/tile_versions")
def tile_versions_json():
    return jsonify({"ok": True, "versions": _scan_tile_versions()})


# --- STATE (POST основной) ---
@bp.post("/state")
def api_state():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    ensure_world_models()
    uid = getattr(u, "id", u)   # строго передаём id, а не объект
    return jsonify(get_world_state(uid))


# --- GET-алиас на тот же контроллер ---
@bp.get("/state")
def api_state_get():
    # используем тот же код, чтобы не дублировать логику
    return api_state()


@bp.post("/set_dest")
def api_set_dest():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    data = request.get_json(silent=True) or request.form or {}
    try:
        x = int(data.get("x"))
        y = int(data.get("y"))
    except Exception:
        return jsonify({"ok": False, "message": "x/y required"}), 400
    uid = getattr(u, "id", u)
    res = set_destination(uid, x, y)
    return jsonify(res), (200 if res.get("ok") else 400)


@bp.post("/stop")
def api_stop():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    uid = getattr(u, "id", u)
    return jsonify(stop_hero(uid))


@bp.post("/rest")
def api_rest():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    uid = getattr(u, "id", u)
    return jsonify(rest_here(uid))


@bp.post("/wake")
def api_wake():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    uid = getattr(u, "id", u)
    return jsonify(wake_up(uid))


@bp.post("/speed")
def api_speed():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    data = request.get_json(silent=True) or request.form or {}
    try:
        sp = float(data.get("speed"))
    except Exception:
        return jsonify({"ok": False, "message": "speed required"}), 400
    uid = getattr(u, "id", u)
    return jsonify(set_speed(uid, sp))


@bp.post("/build")
def api_build():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    kind = (request.json or {}).get("kind") or request.form.get("kind") or ""
    uid = getattr(u, "id", u)
    return jsonify(build_here(uid, kind))


# TEMP CAMP
@bp.post("/camp/start")
def api_camp_start():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    uid = getattr(u, "id", u)
    return jsonify(camp_start(uid))


@bp.post("/camp/leave")
def api_camp_leave():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    uid = getattr(u, "id", u)
    return jsonify(camp_leave(uid))


# --- PATCH VIEW (админ/камеры) ---
@bp.get("/patch")
def api_patch():
    try:
        cx = int(request.args.get("cx"))
        cy = int(request.args.get("cy"))
    except Exception:
        return jsonify({"ok": False, "message": "cx/cy required"}), 400
    # Патч общий (просмотр карты), user_id не требуется
    return jsonify(get_patch_view(cx, cy))
