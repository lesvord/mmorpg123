from typing import Dict

# Базовые тайлы (биомы)
T_GRASS  = "grass"
T_MEADOW = "meadow"
T_FOREST = "forest"
T_SWAMP  = "swamp"
T_SAND   = "sand"
T_DESERT = "desert"
T_WATER  = "water"
T_ROCK   = "rock"
T_SNOW   = "snow"
T_LAVA   = "lava"

# Оверлей-«тайлы» от построек/дорог
T_ROAD   = "road"
T_TOWN   = "town"
T_CAMP   = "camp"
T_TAVERN = "tavern"

def _clamp(v: float, a: float, b: float) -> float:
    return a if v < a else b if v > b else v

# БАЗОВЫЕ атрибуты
# Добавлено: блок sens (чувствительность к экофакторам) — влияет на усталость через tile_env_fatigue_mul().
# sens.{wet,dry,cold,heat} в диапазоне 0..1 (0 — иммунитет).
T_ATTR: Dict[str, dict] = {
    #                speed  pass  fatigue_mul  rest_mul  sens
    T_GRASS:  {"speed":1.00, "pass":True,  "fatigue_mul":1.05, "rest_mul":1.00,
               "sens":{"wet":0.60,"dry":0.40,"cold":0.20,"heat":0.30}},
    T_MEADOW: {"speed":1.05, "pass":True,  "fatigue_mul":1.00, "rest_mul":1.10,
               "sens":{"wet":0.50,"dry":0.30,"cold":0.20,"heat":0.25}},
    T_FOREST: {"speed":0.80, "pass":True,  "fatigue_mul":1.20, "rest_mul":1.00,
               "sens":{"wet":0.80,"dry":0.25,"cold":0.20,"heat":0.35}},
    T_SWAMP:  {"speed":0.60, "pass":True,  "fatigue_mul":1.60, "rest_mul":0.90,
               "sens":{"wet":1.00,"dry":0.05,"cold":0.15,"heat":0.20}},
    T_SAND:   {"speed":0.80, "pass":True,  "fatigue_mul":1.20, "rest_mul":0.95,
               "sens":{"wet":0.20,"dry":0.80,"cold":0.10,"heat":0.60}},
    T_DESERT: {"speed":0.90, "pass":True,  "fatigue_mul":1.35, "rest_mul":0.88,
               "sens":{"wet":0.10,"dry":1.00,"cold":0.10,"heat":0.80}},
    T_WATER:  {"speed":0.00, "pass":False, "fatigue_mul":1.00, "rest_mul":1.00,
               "sens":{"wet":0.00,"dry":0.00,"cold":0.00,"heat":0.00}},
    T_ROCK:   {"speed":0.70, "pass":True,  "fatigue_mul":1.30, "rest_mul":0.95,
               "sens":{"wet":0.40,"dry":0.20,"cold":0.15,"heat":0.20}},
    # усилен снег
    T_SNOW:   {"speed":0.65, "pass":True,  "fatigue_mul":1.55, "rest_mul":0.92,
               "sens":{"wet":0.20,"dry":0.20,"cold":1.00,"heat":0.30}},
    T_LAVA:   {"speed":0.00, "pass":False, "fatigue_mul":1.00, "rest_mul":1.00,
               "sens":{"wet":0.00,"dry":0.00,"cold":0.00,"heat":0.00}},

    # Постройки/дороги
    T_ROAD:   {"speed":1.40, "pass":True,  "fatigue_mul":0.88, "rest_mul":1.00,
               "sens":{"wet":0.25,"dry":0.10,"cold":0.10,"heat":0.10}},
    T_TOWN:   {"speed":1.12, "pass":True,  "fatigue_mul":0.82, "rest_mul":2.20,
               "sens":{"wet":0.10,"dry":0.05,"cold":0.05,"heat":0.05}},
    T_CAMP:   {"speed":1.00, "pass":True,  "fatigue_mul":0.92, "rest_mul":1.70,
               "sens":{"wet":0.10,"dry":0.05,"cold":0.05,"heat":0.05}},
    T_TAVERN: {"speed":1.08, "pass":True,  "fatigue_mul":0.78, "rest_mul":2.50,
               "sens":{"wet":0.05,"dry":0.05,"cold":0.05,"heat":0.05}},
}

# ❄️ Поддержка «скинов» *_snow: поведение как у T_SNOW (единообразно и просто).
_SNOW_SKIN_BASES = ["grass","meadow","forest","swamp","sand","desert","rock","road"]
for _b in _SNOW_SKIN_BASES:
    T_ATTR[f"{_b}_snow"] = dict(T_ATTR[T_SNOW])  # наследуем поведение снега

def _attr(tile: str) -> dict:
    """Безопасный доступ к атрибутам: поддерживает *_snow-тайлы."""
    a = T_ATTR.get(tile)
    if a is not None:
        return a
    if isinstance(tile, str) and tile.endswith("_snow"):
        return T_ATTR[T_SNOW]
    return {}

def is_passable(tile: str) -> bool:
    return bool(_attr(tile).get("pass", False))

def tile_speed(tile: str) -> float:
    return max(0.05, float(_attr(tile).get("speed", 0.0)))

def tile_fatigue_mul(tile: str) -> float:
    return float(_attr(tile).get("fatigue_mul", 1.0))

def tile_rest_mul(tile: str) -> float:
    return float(_attr(tile).get("rest_mul", 1.0))

# --- НОВОЕ: экозависимая прибавка к усталости для обычных биомов ---
def _env_levels(climate: dict, weather: dict):
    """
    Возвращает (wet, dry, cold, heat) в 0..1 из климата и текущей погоды.
    """
    t  = float((climate or {}).get("temp", 0.5))
    m  = float((climate or {}).get("moist", 0.5))
    h  = float((climate or {}).get("height_mean", 0.5))
    f  = float((climate or {}).get("forest_density", 0.0))

    # «эффективная» температура — холоднее в лесу и на высоте
    t_eff = _clamp(t - 0.35*h - 0.06*f, 0.0, 1.0)

    wet  = _clamp((m - 0.55) * 1.8, 0.0, 1.0)
    dry  = _clamp((0.45 - m) * 2.0, 0.0, 1.0)
    cold = _clamp((0.45 - t_eff) * 2.2, 0.0, 1.0)
    heat = _clamp((t_eff - 0.62) * 2.0, 0.0, 1.0)

    key = (weather or {}).get("key", "clear")
    if key == "rain":
        wet = _clamp(wet + 0.35, 0.0, 1.0)
    elif key == "storm":
        wet = _clamp(wet + 0.50, 0.0, 1.0)
    elif key == "snow":
        cold = _clamp(cold + 0.45, 0.0, 1.0)
        wet  = _clamp(wet + 0.15, 0.0, 1.0)
    elif key == "heat":
        heat = _clamp(heat + 0.50, 0.0, 1.0)
        dry  = _clamp(dry  + 0.25, 0.0, 1.0)

    return wet, dry, cold, heat

def tile_env_fatigue_mul(tile: str, climate: dict, weather: dict) -> float:
    """
    Доп. множитель усталости за счёт «условий» (без смены тайла).
    Учтены чувствительности конкретного биома из T_ATTR["sens"].
    """
    a = _attr(tile)
    sens = a.get("sens", {})
    wet_s  = float(sens.get("wet",  0.0))
    dry_s  = float(sens.get("dry",  0.0))
    cold_s = float(sens.get("cold", 0.0))
    heat_s = float(sens.get("heat", 0.0))

    wet, dry, cold, heat = _env_levels(climate or {}, weather or {})

    # Аддитивная модель (стабильнее при больших значениях, чем чисто мультипликативная)
    mul = 1.0 \
        + 0.30 * wet_s  * wet \
        + 0.22 * dry_s  * dry \
        + 0.25 * cold_s * cold \
        + 0.28 * heat_s * heat

    return _clamp(mul, 0.7, 2.0)

# --- public wrapper for UI/debug ---
def env_levels(climate: dict, weather: dict):
    """
    Публичная обёртка для UI/отладки: вернуть уровни среды (wet,dry,cold,heat) в 0..1.
    """
    return _env_levels(climate, weather)
