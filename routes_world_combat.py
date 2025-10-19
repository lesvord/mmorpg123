from __future__ import annotations

from flask import Blueprint, jsonify, request

from helpers import current_user
from world_models import ensure_world_models
from world_combat import (
    combat_snapshot,
    engage_monster,
    attack_monster,
    flee_combat,
)

bp = Blueprint("world_combat", __name__, url_prefix="/world")


def _uid(u) -> int:
    return int(getattr(u, "id", u))


@bp.get("/combat/state")
def combat_state():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    ensure_world_models()
    snap = combat_snapshot(_uid(u))
    return jsonify({"ok": True, "combat": snap})


@bp.post("/combat/engage")
def combat_engage():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    ensure_world_models()
    data = request.get_json(silent=True) or {}
    try:
        monster_id = int(data.get("monster_id"))
    except Exception:
        return jsonify({"ok": False, "message": "monster_id_required"}), 400
    res = engage_monster(_uid(u), monster_id)
    status = 200 if res.get("ok") else 400
    return jsonify(res), status


@bp.post("/combat/attack")
def combat_attack():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    ensure_world_models()
    res = attack_monster(_uid(u))
    status = 200 if res.get("ok") else 400
    return jsonify(res), status


@bp.post("/combat/flee")
def combat_flee():
    u = current_user()
    if not u:
        return jsonify({"ok": False, "message": "no_user"}), 401
    ensure_world_models()
    res = flee_combat(_uid(u))
    status = 200 if res.get("ok") else 400
    return jsonify(res), status
