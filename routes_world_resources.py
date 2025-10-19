# routes_world_resources.py
from __future__ import annotations

import random
from typing import Optional, Tuple

from flask import Blueprint, request, jsonify, g

from models import db
from world_models import ensure_world_models, WorldState
from accounts.models import ItemDef, give_item, inventory_totals
from routes_world import get_world_state  # авторитетное состояние (тайл/погода/усталость)
from gathering_tables import (
    DEFAULT_MODE_KEY,
    DropK,
    normalize_mode,
    serialize_modes,
)

FALLBACK_BIOME = "grass"

bp = Blueprint("world_resources", __name__, url_prefix="/world")

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
MIN_TICK_MS = 2800
BASE_TICK_MS = 4200

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
    base = (tile_id.split("_", 1)[0].strip().lower()) or FALLBACK_BIOME
    return base

def _load_fraction(totals: dict) -> float:
    if not totals:
        return 0.0
    if "load_frac" in totals:
        try:
            return max(0.0, float(totals["load_frac"]))
        except Exception:
            pass
    try:
        return max(0.0, float(totals.get("load_pct", 0.0)) / 100.0)
    except Exception:
        return 0.0

def _weather_difficulty(weather: dict) -> float:
    if not weather:
        return 0.0
    metrics = weather.get("metrics") or {}
    feels = metrics.get("feels_like_c")
    base_temp = metrics.get("temperature_c")
    pivot = feels if isinstance(feels, (int, float)) else base_temp
    temp_penalty = 0.0
    if isinstance(pivot, (int, float)):
        temp_penalty = max(0.0, abs(pivot - 18.0) / 42.0)
    wind_penalty = max(0.0, float(metrics.get("wind_mps") or 0.0) / 14.0)
    precip_penalty = 0.2 if weather.get("precip") in {"rain", "snow"} else 0.0
    return max(0.0, min(1.0, temp_penalty + wind_penalty + precip_penalty))

def _gather_profile(mode, biome: str, weather: dict, load_totals: dict) -> dict:
    load_frac = _load_fraction(load_totals)
    weather_diff = _weather_difficulty(weather)

    windup = DEFAULT_WINDUP_MS * (1.0 + load_frac * 0.6 + weather_diff * 0.35)
    tick_ms = BASE_TICK_MS * (1.0 + load_frac * 0.55 + weather_diff * 0.25)
    tick_ms = max(MIN_TICK_MS, tick_ms)

    bonus_base = 0.35
    if mode.key == "wood" and biome in {"forest", "meadow"}:
        bonus_base += 0.10
    elif mode.key == "ore" and biome in {"rock", "snow", "desert"}:
        bonus_base += 0.08
    elif mode.key == "forage" and biome in {"swamp", "grass", "forest"}:
        bonus_base += 0.05

    bonus_chance = max(0.02, bonus_base - load_frac * 0.28 - weather_diff * 0.22)
    bonus_chain = max(0.0, bonus_chance - 0.18)

    fatigue_mul = float(weather.get("fatigue_mul") or 1.0)
    load_mul = float(load_totals.get("fatigue_mul") or 1.0)

    return {
        "windup_ms": round(windup),
        "tick_ms": round(tick_ms),
        "bonus_chance": bonus_chance,
        "bonus_chain": bonus_chain,
        "fatigue_multiplier": fatigue_mul * load_mul,
        "load_frac": load_frac,
        "weather_diff": weather_diff,
    }

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
def _gather_tick(uid: int, mode_key: str = DEFAULT_MODE_KEY):
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

    totals = inventory_totals(uid)
    load_mul = float(totals.get("fatigue_mul") or 1.0)
    mode = normalize_mode(mode_key)

    profile = _gather_profile(mode, biome, weather, totals)

    base_cost = fatigue_per_tile * GATHER_BASE_FACTOR * load_mul    # «цена тика добычи»

    cur_fat = float(ws.get("fatigue") or 0.0)
    if cur_fat >= 100.0 - 1e-6:
        return {
            "ok": True, "items": [], "message": "Вы выдохлись.",
            "fatigue": cur_fat, "totals": totals, "mode": mode.key,
            "profile": profile,
        }

    # запретная зона — только base_cost
    if biome in ("town", "tavern", "camp"):
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Здесь нечего добывать.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": inventory_totals(uid), "mode": mode.key
        }

    # промах — только base_cost
    miss_adj = _miss_chance(weather_kind, biome)
    # Нагрузка и погода снижают точность
    miss_adj += profile["load_frac"] * 0.18 + profile["weather_diff"] * 0.22
    miss_adj = max(0.10, min(0.82, miss_adj))

    if random.random() < miss_adj:
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Ничего не найдено.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": totals, "mode": mode.key,
            "profile": profile,
        }

    # успех: 1 предмет ×1
    table = mode.table_for(biome)
    key = _weighted_pick(table)

    if not key:
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Ничего не найдено.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": totals, "mode": mode.key,
            "profile": profile,
        }

    # пробуем положить в БД-инвентарь
    qty = 1
    if random.random() < profile["bonus_chance"]:
        qty += 1
        if random.random() < profile["bonus_chain"]:
            qty += 1

    ok, msg, _ = give_item(uid, key, qty=qty, auto_equip=False)
    if not ok:
        # перегруз/ошибка — усилия потрачены: только base_cost
        new_fat = _add_global_fatigue(uid, base_cost)
        human = "Перегруз. Освободите рюкзак." if msg == "overweight" else "Не удалось положить в инвентарь."
        return {
            "ok": True, "items": [], "message": human, "error": msg,
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": totals, "mode": mode.key,
            "profile": profile,
        }

    # успех: base_cost + вес
    extra_per_item = _extra_fatigue_for_weight(key, base_cost)
    extra = extra_per_item * qty
    new_fat = _add_global_fatigue(uid, base_cost + extra)

    name = _item_name(key)
    kg = _item_weight(key)
    icon = _item_icon(key)

    return {
        "ok": True,
        "items": [{
            "key": key,
            "name": name,
            "qty": qty,
            "weight_kg": round(kg, 3),
            "icon": icon
        }],
        "message": f"{mode.title}: {name} ×{qty} ({kg*qty:.2f} кг)",
        "fatigue": new_fat,
        "fatigue_base": round(base_cost, 4),
        "fatigue_extra": round(extra, 4),
        "totals": totals,
        "mode": mode.key,
        "mode_title": mode.title,
        "profile": profile,
    }

# ---------- endpoints ----------
@bp.post("/gather")
def gather():
    uid = _uid()
    if not uid:
        return jsonify({"ok": False, "error": "auth_required"}), 401
    data = request.get_json(silent=True) or {}
    mode_key = data.get("mode") or DEFAULT_MODE_KEY
    return jsonify(_gather_tick(uid, mode_key))

@bp.post("/gather/start")
def gather_start():
    uid = _uid()
    if not uid:
        return jsonify({"ok": False, "error": "auth_required"}), 401
    data = request.get_json(silent=True) or {}
    mode = normalize_mode(data.get("mode"))
    ws = get_world_state(uid)
    totals = inventory_totals(uid)
    profile = _gather_profile(mode, _resolve_biome(ws.get("tile")), ws.get("weather") or {}, totals)

    return jsonify({
        "ok": True,
        "message": "Добыча начата",
        "windup_ms": profile["windup_ms"],
        "tick_ms": profile["tick_ms"],
        "mode": mode.key,
        "modes": serialize_modes(),
        "profile": profile,
        "load": totals,
    })

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
    data = request.get_json(silent=True) or {}
    mode_key = data.get("mode") or DEFAULT_MODE_KEY
    resp = _gather_tick(uid, mode_key)
    return jsonify(resp)
