from __future__ import annotations
import json, math
from typing import Dict, List

from world_tiles import (
    T_GRASS, T_MEADOW, T_FOREST, T_SWAMP, T_SAND, T_DESERT, T_WATER, T_ROCK, T_SNOW, T_LAVA,
    T_ROAD, T_TOWN, T_CAMP, T_TAVERN,
)
from world_tuning import eco_time_accel, eco_half_life, threshold_scale

_NON_MUTABLE = {T_WATER, T_LAVA}               # вода/лава не трогаем
_NON_BIOME_OVERLAYS = {T_ROAD, T_TOWN, T_CAMP, T_TAVERN}

def _clamp(v, a, b): return a if v < a else b if v > b else v

def _h2(x:int, y:int, salt:int=0) -> float:
    h = (x * 73856093) ^ (y * 19349663) ^ (salt * 83492791)
    h &= 0xffffffff
    h = (1664525 * h + 1013904223) & 0xffffffff
    return h / 4294967296.0

def _base_of(tile:str) -> str:
    if not isinstance(tile, str): return tile
    if tile.endswith("_snow"): return tile[:-5]
    return tile

def _decay(val: float, hours: float, half_life_h: float) -> float:
    if hours <= 0: return val
    k = math.exp(-hours / max(0.1, half_life_h))
    return val * k

def _integrate_ecology(eco: Dict[str,float],
                       climate: Dict[str,float],
                       weather: Dict[str,object],
                       dt_seconds: float):
    dt_h = max(0.0, dt_seconds) / 3600.0
    dt_h *= eco_time_accel()   # ускоряем течение времени для экологии
    if dt_h <= 0: return


    t  = float(climate.get("temp", 0.5))
    m  = float(climate.get("moist", 0.5))
    h  = float(climate.get("height_mean", 0.5))
    f  = float(climate.get("forest_density", 0.0))
    key   = (weather or {}).get("key", "clear")
    precip= (weather or {}).get("precip", "none")

    t_eff = _clamp(t - 0.35*h - 0.06*f, 0.0, 1.0)
    wet_inst  = m + (0.18 if precip == "rain" else 0.0) + (0.20 if key == "storm" else 0.0) - (0.06 if key == "heat" else 0.0)
    dry_inst  = (1.0 - m) + (0.12 if key == "heat" else 0.0)
    heat_inst = max(0.0, t_eff - 0.55) + (0.20 if key == "heat" else 0.0)
    cold_inst = max(0.0, 0.45 - t_eff) + 0.10*h + (0.10 if key == "snow" else 0.0)
    forest_inst = (m*0.5 + f*0.6) - (0.25 if key in ("heat","storm") else 0.0)

    eco["wet"]  = _decay(float(eco.get("wet",0.0)),  dt_h, eco_half_life(24.0))  + wet_inst   * dt_h
    eco["dry"]  = _decay(float(eco.get("dry",0.0)),  dt_h, eco_half_life(24.0))  + dry_inst   * dt_h
    eco["heat"] = _decay(float(eco.get("heat",0.0)), dt_h, eco_half_life(24.0))  + heat_inst  * dt_h
    eco["cold"] = _decay(float(eco.get("cold",0.0)), dt_h, eco_half_life(24.0))  + cold_inst  * dt_h
    eco["forest_drive"] = _decay(float(eco.get("forest_drive",0.0)), dt_h, eco_half_life(48.0)) + forest_inst* dt_h

def _mutate_one(base: str,
                eco: Dict[str,float],
                climate: Dict[str,float],
                gx:int, gy:int, salt:int) -> str:
    if base in _NON_MUTABLE or base in _NON_BIOME_OVERLAYS:
        return base

    t  = float(climate.get("temp", 0.5))
    m  = float(climate.get("moist", 0.5))
    h  = float(climate.get("height_mean", 0.5))
    t_eff = _clamp(t - 0.35*h, 0.0, 1.0)

    wet  = float(eco.get("wet",0.0))
    dry  = float(eco.get("dry",0.0))
    heat = float(eco.get("heat",0.0))
    cold = float(eco.get("cold",0.0))
    fr   = float(eco.get("forest_drive",0.0))

    n = _h2(gx, gy, salt)  # 0..1

    TH_SWAMP   = 18.0
    TH_FOREST  = 14.0
    TH_DRY_1   = 20.0
    TH_DRY_2   = 34.0
    TH_RECOVER = 12.0

    if base in (T_GRASS, T_MEADOW, T_FOREST):
        if wet > TH_SWAMP and t_eff > 0.28 and n < 0.45:
            return T_SWAMP

    if base in (T_GRASS, T_MEADOW):
        if fr > TH_FOREST and wet > 8.0 and n < 0.55:
            return T_FOREST

    if base in (T_GRASS, T_MEADOW, T_FOREST):
        dryness = dry + heat*0.7
        if dryness > TH_DRY_2 and t_eff > 0.62 and n < 0.35:
            return T_DESERT
        if dryness > TH_DRY_1 and t_eff > 0.55 and n < 0.50:
            return T_SAND

    if base == T_FOREST:
        if (dry + heat) > (TH_DRY_1 + 4.0) and n < 0.45:
            return T_MEADOW

    if base == T_SWAMP:
        if (dry > TH_RECOVER and heat > 6.0) and n < 0.55:
            return T_MEADOW if wet > 10.0 else T_GRASS

    if base == T_SAND:
        if wet > (TH_SWAMP + 2.0) and cold < 20.0 and n < 0.50:
            return T_GRASS
    if base == T_DESERT:
        if wet > (TH_SWAMP + 4.0) and cold < 18.0 and n < 0.45:
            return T_SAND

    if base == T_ROCK:
        if h < 0.60 and wet > (TH_SWAMP + 6.0) and 0.35 < t_eff < 0.75 and n < 0.25:
            return T_FOREST if fr > 10.0 else T_MEADOW

    return base

def evolve_chunk_persistent(row, climate: Dict[str,float], weather: Dict[str,object],
                            now_ts: float, min_interval_sec: float = 15*60) -> bool:
    last_ts = float(getattr(row, "last_evolve_ts", 0) or 0)
    dt = max(0.0, float(now_ts) - last_ts)
    if dt < min_interval_sec and last_ts > 0:
        return False

    try:
        eco = json.loads(row.eco_json or "{}")
        if not isinstance(eco, dict):
            eco = {}
    except Exception:
        eco = {}
    eco.setdefault("wet", 0.0)
    eco.setdefault("dry", 0.0)
    eco.setdefault("heat", 0.0)
    eco.setdefault("cold", 0.0)
    eco.setdefault("forest_drive", 0.0)
    eco.setdefault("seed", (row.cx * 911 + row.cy * 613) & 0xffffffff)

    _integrate_ecology(eco, climate or {}, weather or {}, dt or min_interval_sec)

    try:
        tiles: List[List[str]] = json.loads(row.tiles_json or "[]")
    except Exception:
        tiles = []

    size = int(row.size or 32)
    ox = int(row.cx) * size
    oy = int(row.cy) * size
    salt = int(eco.get("seed", 0)) ^ int(now_ts // (60*60*6))

    changed = False
    if tiles:
        h = len(tiles); w = len(tiles[0]) if h>0 else 0
        for j in range(h):
            for i in range(w):
                t = _base_of(tiles[j][i])
                if t in _NON_BIOME_OVERLAYS or t in _NON_MUTABLE:
                    continue
                nx = _mutate_one(t, eco, climate or {}, ox+i, oy+j, salt)
                if nx != t:
                    tiles[j][i] = nx
                    changed = True

    row.last_evolve_ts = float(now_ts)
    row.eco_json = json.dumps({
        "wet": float(eco.get("wet",0.0)),
        "dry": float(eco.get("dry",0.0)),
        "heat": float(eco.get("heat",0.0)),
        "cold": float(eco.get("cold",0.0)),
        "forest_drive": float(eco.get("forest_drive",0.0)),
        "seed": int(eco.get("seed",0)),
    }, separators=(",",":"))

    if changed:
        row.tiles_json = json.dumps(tiles, separators=(",",":"))

    return changed
