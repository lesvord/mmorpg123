# routes_admin.py
import base64
import os
import time
from typing import Optional, Dict, Any

from flask import (
    Blueprint, current_app, request, jsonify, render_template,
    make_response
)

from world_models import db, ensure_world_models, WorldOverride, WorldBuilding, WorldChunk
from services_world import get_patch_view

bp = Blueprint("admin", __name__, url_prefix="/admin")


# ======= Простая HTTP Basic "админка" =======
def _admin_auth_ok() -> bool:
    """Проверяем HTTP Basic пароль (юзер любой, пароль сравнивается с ADMIN_PASS)."""
    auth = request.authorization
    if not auth:
        # Попытка распарсить вручную (некоторые клиенты не заполняют request.authorization)
        hdr = request.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                raw = base64.b64decode(hdr.split(" ", 1)[1]).decode("utf-8", "ignore")
                # формат: username:password
                parts = raw.split(":", 1)
                if len(parts) == 2:
                    auth = type("Auth", (), {"username": parts[0], "password": parts[1]})
            except Exception:
                pass

    if not auth:
        return False
    want = current_app.config.get("ADMIN_PASS", "les")
    return auth.password == want


def _require_admin():
    if not _admin_auth_ok():
        resp = make_response("Auth required", 401)
        resp.headers["WWW-Authenticate"] = 'Basic realm="admin"'
        return resp
    return None


# ======= Вспомогательное: мэп версий ассетов для фронта =======
def _scan_tile_versions() -> Dict[str, int]:
    """
    Отдаём {filename.ext: int(mtime)} из static/tiles.
    Нужен для cache-busting и выбора доступных форматов (avif/webp/png, @1x/@2x).
    """
    root = os.path.join(current_app.static_folder, "tiles")
    out: Dict[str, int] = {}
    try:
        for fn in os.listdir(root):
            if not (fn.lower().endswith(".png") or fn.lower().endswith(".webp") or fn.lower().endswith(".avif")):
                continue
            full = os.path.join(root, fn)
            try:
                out[fn] = int(os.path.getmtime(full))
            except Exception:
                out[fn] = int(time.time())
    except Exception:
        pass
    return out


# ===================== VIEW ======================
@bp.get("/")
def page():
    guard = _require_admin()
    if guard is not None:
        return guard
    ensure_world_models()
    return render_template("admin_map.html", tile_versions=_scan_tile_versions())


# Лёгкий endpoints для фронта (обновляет список известных файлов тайлов)
@bp.get("/tile_versions")
def tile_versions_json():
    guard = _require_admin()
    if guard is not None:
        return guard
    return jsonify({"ok": True, "versions": _scan_tile_versions()})


# Патч карты вокруг произвольной точки — для бесконечной прокрутки
@bp.get("/patch")
def api_patch():
    guard = _require_admin()
    if guard is not None:
        return guard
    try:
        cx = int(request.args.get("cx", "0"))
        cy = int(request.args.get("cy", "0"))
    except Exception:
        return jsonify({"ok": False, "message": "cx, cy required"}), 400
    ensure_world_models()
    data = get_patch_view(cx, cy)  # {"ok": True, "patch": {...}}
    return jsonify(data)


# ======= Редактирование тайлов (биом) =======
@bp.post("/set_tile")
def api_set_tile():
    guard = _require_admin()
    if guard is not None:
        return guard
    j = request.get_json(silent=True) or {}
    try:
        x = int(j.get("x"))
        y = int(j.get("y"))
        tile_id = str(j.get("tile")).strip()
        reason = str(j.get("reason") or "")[:120]
    except Exception:
        return jsonify({"ok": False, "message": "x,y,tile required"}), 400

    if not tile_id:
        return jsonify({"ok": False, "message": "tile required"}), 400

    ensure_world_models()
    row = WorldOverride.query.filter_by(x=x, y=y).first()
    if row:
        row.tile_id = tile_id
        row.reason = reason
    else:
        row = WorldOverride(x=x, y=y, tile_id=tile_id, reason=reason, author_id="admin", created_at=time.time())
        db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "message": f"Tile at ({x},{y}) -> {tile_id}"})


@bp.post("/clear_tile")
def api_clear_tile():
    guard = _require_admin()
    if guard is not None:
        return guard
    j = request.get_json(silent=True) or {}
    try:
        x = int(j.get("x")); y = int(j.get("y"))
    except Exception:
        return jsonify({"ok": False, "message": "x,y required"}), 400

    ensure_world_models()
    row = WorldOverride.query.filter_by(x=x, y=y).first()
    if row:
        db.session.delete(row)
        db.session.commit()
        return jsonify({"ok": True, "message": "override removed"})
    return jsonify({"ok": True, "message": "nothing to remove"})


# ======= Постройки (town/tavern/road/camp ad-hoc) =======
@bp.post("/set_building")
def api_set_building():
    guard = _require_admin()
    if guard is not None:
        return guard
    j = request.get_json(silent=True) or {}
    try:
        x = int(j.get("x")); y = int(j.get("y"))
        kind = str(j.get("kind")).strip()
    except Exception:
        return jsonify({"ok": False, "message": "x,y,kind required"}), 400
    if not kind:
        return jsonify({"ok": False, "message": "kind required"}), 400

    ensure_world_models()
    existing = WorldBuilding.query.filter_by(x=x, y=y).first()
    if existing:
        existing.kind = kind
    else:
        db.session.add(WorldBuilding(x=x, y=y, kind=kind, owner_id="admin", data_json="{}", created_at=time.time()))
    db.session.commit()
    return jsonify({"ok": True})


@bp.post("/del_building")
def api_del_building():
    guard = _require_admin()
    if guard is not None:
        return guard
    j = request.get_json(silent=True) or {}
    try:
        x = int(j.get("x")); y = int(j.get("y"))
    except Exception:
        return jsonify({"ok": False, "message": "x,y required"}), 400

    ensure_world_models()
    existing = WorldBuilding.query.filter_by(x=x, y=y).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"ok": True, "message": "building removed"})
    return jsonify({"ok": True, "message": "nothing to remove"})


# ======= Климат чанка (простая правка temp/moist/forest_density) =======
@bp.post("/set_climate")
def api_set_climate():
    guard = _require_admin()
    if guard is not None:
        return guard
    j = request.get_json(silent=True) or {}
    try:
        x = int(j.get("x")); y = int(j.get("y"))
        temp = float(j.get("temp"))
        moist = float(j.get("moist"))
        forest = float(j.get("forest_density"))
    except Exception:
        return jsonify({"ok": False, "message": "x,y,temp,moist,forest_density required"}), 400

    ensure_world_models()
    # Найдём чанк (как в services_world._chunk_of_xy)
    CHUNK_SIZE = 32
    cx = (x // CHUNK_SIZE) if x >= 0 else -((abs(x) + CHUNK_SIZE - 1) // CHUNK_SIZE)
    cy = (y // CHUNK_SIZE) if y >= 0 else -((abs(y) + CHUNK_SIZE - 1) // CHUNK_SIZE)
    row = WorldChunk.query.filter_by(cx=cx, cy=cy).first()
    if not row:
        # форс-генерация патчем
        get_patch_view(x, y)
        row = WorldChunk.query.filter_by(cx=cx, cy=cy).first()
    if not row:
        return jsonify({"ok": False, "message": "chunk not found"}), 404

    import json as _json
    try:
        clim = _json.loads(row.climate_json or "{}")
    except Exception:
        clim = {}
    clim["temp"] = max(0.0, min(1.0, temp))
    clim["moist"] = max(0.0, min(1.0, moist))
    clim["forest_density"] = max(0.0, min(1.0, forest))
    row.climate_json = _json.dumps(clim)
    db.session.add(row)
    db.session.commit()
    return jsonify({"ok": True, "message": "climate updated", "climate": clim})
