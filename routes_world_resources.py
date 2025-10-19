# routes_world_resources.py
from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

from flask import Blueprint, request, jsonify, g

from models import db
from world_models import ensure_world_models, WorldState
from accounts.models import ItemDef, PlayerProfile, give_item, inventory_totals
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

def _player_stats(uid: int) -> Dict[str, float]:
    try:
        row = PlayerProfile.query.filter_by(user_id=uid).first()
        if not row:
            return {}
        snap = row.as_dict()
        # Добавим явные алиасы для удобства вычислений
        snap.setdefault("level", snap.get("lvl", row.level))
        snap.setdefault("str", getattr(row, "str_", snap.get("str", 5)))
        snap.setdefault("agi", getattr(row, "agi", snap.get("agi", 5)))
        snap.setdefault("vit", getattr(row, "vit", snap.get("vit", 5)))
        snap.setdefault("luck", getattr(row, "luck", snap.get("luck", 1)))
        return snap
    except Exception:
        return {}


def _gather_profile(mode, biome: str, weather: dict, load_totals: dict, player_stats: Optional[Dict[str, float]] = None) -> dict:
    load_frac = _load_fraction(load_totals)
    weather_diff = _weather_difficulty(weather)

    stats = player_stats or {}
    level = max(1, int(stats.get("level") or stats.get("lvl") or 1))
    str_score = max(1, int(stats.get("str") or stats.get("str_", 5)))
    agi_score = max(1, int(stats.get("agi") or 5))
    vit_score = max(1, int(stats.get("vit") or 5))
    luck_score = max(0, int(stats.get("luck") or 0))

    gather_skill = (str_score * 0.45) + (agi_score * 0.55) + (luck_score * 0.25) + (level * 0.9)
    baseline_skill = (5 * 0.45) + (5 * 0.55) + (1 * 0.25) + (1 * 0.9)
    skill_ratio = gather_skill / baseline_skill if baseline_skill else 1.0
    skill_ratio = max(0.45, min(2.2, skill_ratio))

    speed_mod = 1.0 - (skill_ratio - 1.0) * 0.35
    speed_mod = max(0.55, min(1.35, speed_mod))

    endurance_score = (str_score * 0.6) + (vit_score * 0.4)
    baseline_endurance = (5 * 0.6) + (5 * 0.4)
    endurance_ratio = endurance_score / baseline_endurance if baseline_endurance else 1.0
    endurance_ratio = max(0.4, min(2.2, endurance_ratio))
    fatigue_stat_mod = 1.0 - (endurance_ratio - 1.0) * 0.3
    fatigue_stat_mod = max(0.55, min(1.35, fatigue_stat_mod))

    luck_bonus = min(0.22, max(0.0, luck_score * 0.006 + agi_score * 0.0025))
    chain_bonus = min(0.18, max(0.0, luck_score * 0.003))

    windup = DEFAULT_WINDUP_MS * (1.0 + load_frac * 0.6 + weather_diff * 0.35)
    tick_ms = BASE_TICK_MS * (1.0 + load_frac * 0.55 + weather_diff * 0.25)
    windup *= speed_mod
    tick_ms *= speed_mod * (0.88 + min(0.08, level * 0.01))
    tick_ms = max(MIN_TICK_MS, tick_ms)

    bonus_base = 0.35
    if mode.key == "wood" and biome in {"forest", "meadow"}:
        bonus_base += 0.10
    elif mode.key == "ore" and biome in {"rock", "snow", "desert"}:
        bonus_base += 0.08
    elif mode.key == "forage" and biome in {"swamp", "grass", "forest"}:
        bonus_base += 0.05

    bonus_chance = max(0.02, bonus_base - load_frac * 0.28 - weather_diff * 0.22)
    bonus_chance = min(0.9, bonus_chance + luck_bonus)
    bonus_chain = max(0.0, bonus_chance - 0.18 + chain_bonus)

    weather_fatigue = float(
        weather.get("fatigue_mul")
        or (weather.get("mods") or {}).get("fatigue_mul")
        or 1.0
    )
    load_mul = float(load_totals.get("fatigue_mul") or 1.0)
    combined_fatigue = weather_fatigue * load_mul * fatigue_stat_mod

    return {
        "windup_ms": round(windup),
        "tick_ms": round(tick_ms),
        "bonus_chance": bonus_chance,
        "bonus_chain": bonus_chain,
        "fatigue_multiplier": combined_fatigue,
        "load_frac": load_frac,
        "weather_diff": weather_diff,
        "stat_mods": {
            "skill_ratio": round(skill_ratio, 3),
            "speed_mod": round(speed_mod, 3),
            "fatigue_mod": round(fatigue_stat_mod, 3),
            "luck_bonus": round(luck_bonus, 3),
        },
    }

def _miss_chance(weather_kind: str, biome: str, player_stats: Optional[Dict[str, float]] = None) -> float:
    w = (weather_kind or "").lower()
    miss = BASE_MISS
    if w == "storm": miss += 0.15
    elif w == "rain": miss += 0.05
    elif w == "snow": miss += 0.07
    elif w == "heat": miss += 0.04
    if biome in ("water","swamp") and w in ("rain","storm"): miss -= 0.05
    if biome == "rock" and w in ("rain","storm"): miss += 0.04
    if player_stats:
        agi_score = max(1, int(player_stats.get("agi") or 0))
        luck_score = max(0, int(player_stats.get("luck") or 0))
        lvl = max(1, int(player_stats.get("level") or player_stats.get("lvl") or 1))
        miss -= min(0.2, max(0.0, (agi_score - 5) * 0.015 + luck_score * 0.004 + (lvl - 1) * 0.003))
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
    stats = _player_stats(uid)
    mode = normalize_mode(mode_key)

    profile = _gather_profile(mode, biome, weather, totals, stats)

    fatigue_mul = float(profile.get("fatigue_multiplier") or 1.0)
    base_cost = fatigue_per_tile * GATHER_BASE_FACTOR * fatigue_mul    # «цена тика добычи»

    cur_fat = float(ws.get("fatigue") or 0.0)
    if cur_fat >= 100.0 - 1e-6:
        return {
            "ok": True, "items": [], "message": "Вы выдохлись.",
            "fatigue": cur_fat, "totals": totals, "mode": mode.key,
            "profile": profile,
            "player_stats": stats,
        }

    # запретная зона — только base_cost
    if biome in ("town", "tavern", "camp"):
        new_fat = _add_global_fatigue(uid, base_cost)
        return {
            "ok": True, "items": [], "message": "Здесь нечего добывать.",
            "fatigue": new_fat, "fatigue_base": base_cost, "fatigue_extra": 0.0,
            "totals": inventory_totals(uid), "mode": mode.key,
            "profile": profile,
            "player_stats": stats,
        }

    # промах — только base_cost
    miss_adj = _miss_chance(weather_kind, biome, stats)
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
            "player_stats": stats,
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
            "player_stats": stats,
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
            "player_stats": stats,
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
        "player_stats": stats,
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
    stats = _player_stats(uid)
    profile = _gather_profile(mode, _resolve_biome(ws.get("tile")), ws.get("weather") or {}, totals, stats)

    return jsonify({
        "ok": True,
        "message": "Добыча начата",
        "windup_ms": profile["windup_ms"],
        "tick_ms": profile["tick_ms"],
        "mode": mode.key,
        "modes": serialize_modes(),
        "profile": profile,
        "load": totals,
        "player_stats": stats,
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
