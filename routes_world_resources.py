# routes_world_resources.py
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, Tuple, Optional

from flask import Blueprint, request, jsonify, g

from models import db
from world_models import ensure_world_models, WorldState
from accounts.models import ItemDef, give_item, inventory_totals
from routes_world import get_world_state  # авторитетное состояние (тайл/погода/усталость)

bp = Blueprint("world_resources", __name__, url_prefix="/world")

# ---------- дроп-таблицы (биом -> ключи ItemDef) ----------
@dataclass(frozen=True)
class DropK:
    key: str
    w: int

BIOMES: Dict[str, Tuple[DropK, ...]] = {
    "grass":  (DropK("res_stick", 9),  DropK("res_fiber", 7),   DropK("res_berries", 5), DropK("res_herb", 3),   DropK("res_stone", 3)),
    "forest": (DropK("res_stick",10),  DropK("res_wood_log", 6),DropK("res_mushroom",5), DropK("res_berries",4), DropK("res_stone",2)),
    "swamp":  (DropK("res_reed", 8),   DropK("res_clay", 6),    DropK("res_peat", 5),    DropK("res_mushroom",3),DropK("res_fish",2)),
    "rock":   (DropK("res_stone", 9),  DropK("res_copper_ore",5),DropK("res_iron_ore",4), DropK("res_gold_nug",1),DropK("res_gem",1)),
    "sand":   (DropK("res_sand",10),   DropK("res_stone", 3),   DropK("res_cactus", 3),  DropK("res_gold_nug",1)),
    "desert": (DropK("res_sand",10),   DropK("res_cactus", 4),  DropK("res_stone", 3),   DropK("res_gold_nug",1)),
    "water":  (DropK("res_fish", 6),   DropK("res_reed", 6),    DropK("res_sand", 2)),
    "snow":   (DropK("res_ice", 8),    DropK("res_stone", 3),   DropK("res_berries",1)),
    "lava":   (DropK("res_obsidian",2),DropK("res_stone", 4),   DropK("res_gem", 1)),
    "road":   (DropK("res_stick", 3),  DropK("res_stone", 3)),
    "town": tuple(), "tavern": tuple(), "camp": tuple(),
}
FALLBACK_BIOME = "grass"

BASE_MISS = 0.40  # базовый шанс промаха

# ---------- СИЛА добычи (жёстче, чем движение) ----------
# Базовая «цена шага» берётся из weather.mods.fatigue_per_tile (см. routes_world.get_world_state).
# Для добычи множим её, чтобы усталость росла заметно.
GATHER_BASE_FACTOR = 4.0

# Доплата за вес найденного предмета (существенная):
# extra = base_cost * min(WEIGHT_CAP, WEIGHT_ALPHA * (item_kg / WEIGHT_BASE_KG))
WEIGHT_ALPHA     = 2.0     # +200% базовой цены на каждый килограмм
WEIGHT_BASE_KG   = 1.00
WEIGHT_CAP       = 6.0     # потолок доплаты: до +600% от base (итого base * 7 максимум)

# Сколько клиенту «греться» перед первым тиком (можно менять динамически)
DEFAULT_WINDUP_MS = 2000

# ---------- helpers ----------
def _uid() -> Optional[int]:
    u = getattr(g, "user", None)
    if not u:
        return None
    try:
        return int(getattr(u, "id", 0) or 0) or None
    except Exception:
        return None

def _resolve_biome(tile_id: Optional[str]) -> str:
    if not tile_id:
        return FALLBACK_BIOME
    return (tile_id.split("_", 1)[0].strip().lower()) or FALLBACK_BIOME

def _miss_chance(weather_kind: str, biome: str) -> float:
    w = (weather_kind or "").lower()
    miss = BASE_MISS
    if w == "storm": miss += 0.15
    elif w == "rain": miss += 0.05
    elif w == "snow": miss += 0.07
    elif w == "heat": miss += 0.04
    if biome in ("water","swamp") and w in ("rain","storm"): miss -= 0.05
    if biome == "rock" and w in ("rain","storm"): miss += 0.04
    return max(0.15, min(0.70, miss))

def _weighted_pick(table: Tuple[DropK, ...]) -> Optional[str]:
    if not table: return None
    s = sum(max(0, x.w) for x in table)
    if s <= 0: return None
    r = random.random() * s
    acc = 0.0
    for x in table:
        acc += max(0, x.w)
        if r <= acc:
            return x.key
    return table[-1].key

def _item_by_key(key: str) -> Optional[ItemDef]:
    try:
        return ItemDef.query.filter_by(key=key).first()
    except Exception:
        return None

def _item_name(key: str) -> str:
    row = _item_by_key(key)
    return row.name if row else key

def _item_weight(key: str) -> float:
    row = _item_by_key(key)
    try:
        return float(row.weight_kg or 0.0) if row else 0.0
    except Exception:
        return 0.0

def _item_icon(key: str) -> Optional[str]:
    row = _item_by_key(key)
    return row.icon if row else None

def _extra_fatigue_for_weight(item_key: str, base_cost: float) -> float:
    kg = _item_weight(item_key)
    if kg <= 0:
        return 0.0
    extra_mul = WEIGHT_ALPHA * (kg / WEIGHT_BASE_KG)
    extra_mul = max(0.0, min(WEIGHT_CAP, extra_mul))
    return base_cost * extra_mul

def _add_global_fatigue(uid: int, dv: float) -> float:
    """
    Прибавляет усталость в ту же модель, что использует двигатель движения (WorldState.fatigue).
    """
    ensure_world_models()
    uid_s = str(uid)
    row = WorldState.query.filter_by(user_id=uid_s).first()
    if not row:
        get_world_state(uid)  # создаст при отсутствии
        row = WorldState.query.filter_by(user_id=uid_s).first()
        if not row:
            return 0.0
    cur = float(row.fatigue or 0.0)
    cur = max(0.0, min(100.0, cur + float(dv or 0.0)))
    row.fatigue = cur
    db.session.add(row); db.session.commit()
    return cur

# ---------- основной тик ----------
def _gather_tick(uid: int):
    """
    Один тик добычи:
      - списываем базовую цену (fatigue_per_tile × GATHER_BASE_FACTOR),
      - промах/запретная зона: только base,
      - успех: 1 предмет ×1 и доп. усталость за вес.
    """
    ws = get_world_state(uid)  # авторитетное состояние (даёт weather.mods.fatigue_per_tile)
    tile_id = ws.get("tile") or ""
    biome = _resolve_biome(tile_id)
    weather = ws.get("weather") or {}
    weather_kind = (weather.get("kind") or weather.get("id") or weather.get("name") or "").lower()
    mods = weather.get("mods") or {}
    fatigue_per_tile = float(mods.get("fatigue_per_tile") or 0.8)  # «цена шага»
    base_cost = fatigue_per_tile * GATHER_BASE_FACTOR              # «цена тика добычи»

    cur_fat = float(ws.get("fatigue") or 0.0)
    if cur_fat >= 100.0 - 1e-6:
        return {
            "ok": True, "items": [], "message": "Вы выдохлись.",
            "fatigue": cur_fat, "totals": inventory_totals(uid)
        }

    # запретная зона — только base_cost
    if biome in ("town", "tavern", "camp"):
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Здесь нечего добывать.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": inventory_totals(uid)
        }

    # промах — только base_cost
    if random.random() < _miss_chance(weather_kind, biome):
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Ничего не найдено.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": inventory_totals(uid)
        }

    # успех: 1 предмет ×1
    table = BIOMES.get(biome) or BIOMES[FALLBACK_BIOME]
    key = _weighted_pick(table)

    if not key:
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Ничего не найдено.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": inventory_totals(uid)
        }

    # пробуем положить в БД-инвентарь
    ok, msg, _ = give_item(uid, key, qty=1, auto_equip=False)
    if not ok:
        # перегруз/ошибка — усилия потрачены: только base_cost
        new_fat = _add_global_fatigue(uid, base_cost)
        human = "Перегруз. Освободите рюкзак." if msg == "overweight" else "Не удалось положить в инвентарь."
        return {
            "ok": True, "items": [], "message": human, "error": msg,
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": inventory_totals(uid)
        }

    # успех: base_cost + вес
    extra = _extra_fatigue_for_weight(key, base_cost)
    new_fat = _add_global_fatigue(uid, base_cost + extra)

    name = _item_name(key)
    kg = _item_weight(key)
    icon = _item_icon(key)

    return {
        "ok": True,
        "items": [{
            "key": key,
            "name": name,
            "qty": 1,
            "weight_kg": round(kg, 3),
            "icon": icon
        }],
        "message": f"Добыто: {name} ×1 ({kg:.2f} кг)",
        "fatigue": new_fat,
        "fatigue_base": round(base_cost, 4),
        "fatigue_extra": round(extra, 4),
        "totals": inventory_totals(uid),
    }

# ---------- endpoints ----------
@bp.post("/gather")
def gather():
    uid = _uid()
    if not uid:
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return jsonify(_gather_tick(uid))

@bp.post("/gather/start")
def gather_start():
    if not _uid():
        return jsonify({"ok": False, "error": "auth_required"}), 401
    # можно динамически менять windup, например, от биома/инструмента
    return jsonify({"ok": True, "message": "Добыча начата", "windup_ms": DEFAULT_WINDUP_MS})

@bp.post("/gather/stop")
def gather_stop():
    if not _uid():
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return jsonify({"ok": True, "message": "Добыча остановлена"})

@bp.post("/gather/tick")
def gather_tick():
    uid = _uid()
    if not uid:
        return jsonify({"ok": False, "error": "auth_required"}), 401
    return jsonify(_gather_tick(uid))
