# routes_inventory.py
from __future__ import annotations

from flask import Blueprint, jsonify, request, g
from models import db
from accounts.models import (
    InventoryItem,
    ItemDef,
    give_item,
    drop_item,
    inventory_totals,
)

# Единый API префикс
bp = Blueprint("inventory_api", __name__, url_prefix="/inv/api")


def _serialize_row(r: InventoryItem) -> dict:
    item: ItemDef | None = r.item
    weight_kg = float(item.weight_kg) if item and item.weight_kg is not None else 0.0
    stack_max = int(item.stack_max) if item and item.stack_max is not None else 99
    name = item.name if item else None
    key = item.key if item else None
    icon = item.icon if item else None
    typ  = item.type if item else None
    qty = int(r.qty or 0)
    return {
        "inv_id": r.id,
        "item_key": key,
        "name": name,
        "type": typ,
        "icon": (f"/static/icons/items/{icon}.png" if icon else None),
        "qty": qty,
        "weight_kg": weight_kg,
        "stack_max": stack_max,
        "total_weight": round(weight_kg * qty, 3),
        "equipped": bool(r.equipped),
        "slot": r.slot,
    }


@bp.get("/list")
def api_list():
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401

    rows = (
        db.session.query(InventoryItem)
        .join(ItemDef, ItemDef.id == InventoryItem.item_id)
        .filter(InventoryItem.user_id == g.user.id, InventoryItem.qty > 0)
        .order_by(ItemDef.key.asc(), InventoryItem.id.asc())
        .all()
    )
    items = [_serialize_row(r) for r in rows]
    totals = inventory_totals(g.user.id)  # {"weight_kg","capacity_kg","load_pct"}
    counts = {
        "stacks": len(rows),
        "pieces": sum(int(r.qty or 0) for r in rows),
    }
    return jsonify({"ok": True, "items": items, "totals": totals, "counts": counts})


@bp.post("/drop")
def api_drop():
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401

    data = request.get_json(silent=True) or {}
    inv_id = int(data.get("inv_id") or 0)
    qty = int(data.get("qty") or 0)
    if inv_id <= 0 or qty <= 0:
        return jsonify({"ok": False, "error": "bad_args"}), 400

    ok, msg = drop_item(g.user.id, inv_id, qty)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    totals = inventory_totals(g.user.id)
    return jsonify({"ok": True, "message": msg, "totals": totals})


@bp.post("/add")
def api_add():
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401

    data = request.get_json(silent=True) or {}
    key = (data.get("key") or "").strip()
    qty = int(data.get("qty") or 1)
    if not key or qty <= 0:
        return jsonify({"ok": False, "error": "bad_args"}), 400

    ok, msg, inv_id = give_item(g.user.id, key, qty, auto_equip=False)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    totals = inventory_totals(g.user.id)
    return jsonify({"ok": True, "message": msg, "inv_id": inv_id, "totals": totals})
