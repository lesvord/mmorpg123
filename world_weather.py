# world_weather.py — пространственно связная погода с мягкими переходами

from __future__ import annotations
import math, random
from typing import Dict, Optional
from collections import OrderedDict
from world_tuning import weather_slot_seconds

# ---------------- small LRU ----------------
_WEATHER_CACHE: "OrderedDict[tuple, Dict[str,object]]" = OrderedDict()
_WEATHER_CACHE_MAX = 1024

def _cache_get(k: tuple):
    v = _WEATHER_CACHE.get(k)
    if v is not None:
        _WEATHER_CACHE.move_to_end(k)
    return v

def _cache_put(k: tuple, v: Dict[str,object]):
    _WEATHER_CACHE[k] = v
    _WEATHER_CACHE.move_to_end(k)
    if len(_WEATHER_CACHE) > _WEATHER_CACHE_MAX:
        _WEATHER_CACHE.popitem(last=False)

# ---------------- base utils ----------------
def _clamp(v, a, b):
    return a if v < a else b if v > b else v

def _lerp(a, b, t):
    return a + (b - a) * t

def _smoothstep(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)

def _season(now_slot_seconds: float) -> float:
    year_half = 182.5 * 86400.0
    return math.sin((now_slot_seconds % year_half) / year_half * 2.0 * math.pi)

def _day_night(now_slot_seconds: float) -> float:
    day = 86400.0
    return math.sin((now_slot_seconds % day) / day * 2.0 * math.pi)

def _seed_from(cl: Dict[str, float], now_slot_seconds: float) -> int:
    s = int(now_slot_seconds) ^ int((cl.get("temp", .5))*1e6) ^ int((cl.get("moist", .5))*1e6) ^ int((cl.get("height_mean", .5))*1e6)
    return s & 0x7fffffff

# Период погоды (сек): делаем длиннее, чтобы состояния сменялись реже
WEATHER_SLOT_SEC = weather_slot_seconds()

# ------------- coherent value noise (deterministic) -------------
def _hash32(x:int, y:int, slot:int, chan:int=0) -> int:
    h = (x * 374761393) ^ (y * 668265263) ^ (slot * 1442695040888963407 & 0xffffffff) ^ (chan*2654435761)
    h = (h ^ (h >> 13)) & 0xffffffff
    h = (h * 1274126177) & 0xffffffff
    h = (h ^ (h >> 16)) & 0xffffffff
    return h

def _rand01(x:int, y:int, slot:int, chan:int=0) -> float:
    return _hash32(x, y, slot, chan) / 4294967296.0

def _value_noise_2d(x: float, y: float, slot:int, chan:int=0) -> float:
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    sfx, sfy = _smoothstep(fx), _smoothstep(fy)
    v00 = _rand01(ix+0, iy+0, slot, chan)
    v10 = _rand01(ix+1, iy+0, slot, chan)
    v01 = _rand01(ix+0, iy+1, slot, chan)
    v11 = _rand01(ix+1, iy+1, slot, chan)
    vx0 = _lerp(v00, v10, sfx)
    vx1 = _lerp(v01, v11, sfx)
    return _lerp(vx0, vx1, sfy)

def _fbm2(x: float, y: float, slot:int, chan:int=0, octaves:int=2, lacunarity:float=2.0, gain:float=0.5) -> float:
    amp = 1.0
    freq = 1.0
    s = 0.0
    norm = 0.0
    for _ in range(max(1, octaves)):
        s += _value_noise_2d(x*freq, y*freq, slot, chan) * amp
        norm += amp
        amp *= gain
        freq *= lacunarity
    return s / max(1e-6, norm)

def _q(x: float, step: float) -> int:
    """Квантование для ключа кэша (стабильно и дешево)."""
    return int(_clamp(x, 0.0, 1.0) / step) if step > 0 else int(x)

# ---------------- main picker ----------------
def pick_weather_for_chunk(climate: Dict[str,float],
                           urbanization: float,
                           now_bucket: float,
                           *,
                           cx: Optional[int]=None,
                           cy: Optional[int]=None,
                           now_ts: Optional[float]=None) -> Dict[str, object]:
    """
    Возвращает погодное состояние с коррелированными по пространству полями.
    КЭШИРУЕТСЯ по (cx,cy, slotA/slotB, alpha_q, климату и урбанизации).
    """
    t  = float(climate.get("temp", 0.5))
    m  = float(climate.get("moist", 0.5))
    h  = float(climate.get("height_mean", 0.5))
    f  = float(climate.get("forest_density", 0.0))

    seas = _season(now_bucket)
    dn   = _day_night(now_bucket)

    t_eff = t + 0.35*seas + 0.08*dn - 0.35*h + 0.10*float(urbanization or 0.0)
    t_eff = _clamp(t_eff, 0.0, 1.0)

    _cx = int(cx) if cx is not None else 0
    _cy = int(cy) if cy is not None else 0

    SCALE_PRECIP = 4.0
    SCALE_STORM  = 5.0
    SCALE_FOG    = 4.0
    SCALE_TEMP   = 8.0

    slot0 = int(now_bucket // WEATHER_SLOT_SEC)
    if now_ts is None:
        alpha = 0.0
        slotA = slot0
        slotB = slot0
    else:
        start = math.floor(now_ts / WEATHER_SLOT_SEC) * WEATHER_SLOT_SEC
        frac  = _clamp((now_ts - start) / WEATHER_SLOT_SEC, 0.0, 1.0)
        alpha = _smoothstep(frac)
        slotA = slot0
        slotB = slot0 + 1

    # --- попробуем кэш ---
    key = (
        _cx, _cy, slotA, slotB, _q(alpha, 0.05),
        _q(t, 0.02), _q(m, 0.02), _q(h, 0.02), _q(f, 0.02),
        _q(float(urbanization or 0.0), 0.1)
    )
    cached = _cache_get(key)
    if cached is not None:
        # возвращаем копию, чтобы никто не портил кэш
        return dict(cached)

    def field(scale: float, chan:int) -> float:
        ax = _cx / scale
        ay = _cy / scale
        fa = _fbm2(ax, ay, slotA, chan=chan, octaves=2)
        fb = _fbm2(ax, ay, slotB, chan=chan, octaves=2)
        return _lerp(fa, fb, alpha)

    precip_field = field(SCALE_PRECIP, 11)
    storm_field  = field(SCALE_STORM,  22)
    fog_field    = field(SCALE_FOG,    33)
    temp_anom    = field(SCALE_TEMP,   44)

    t_eff2 = _clamp(t_eff + (temp_anom - 0.5)*0.16, 0.0, 1.0)

    w_clear = 0.3 + (0.4 - m) * 0.9
    w_fog   = max(0.0, (m - 0.55) * (0.5 + 0.5*f))
    w_wind  = 0.15 + abs(_season(now_bucket)) * 0.15
    w_storm = max(0.0, (m - 0.60)*(0.6 - f*0.2))

    w_heat  = max(0.0, (t_eff2 - 0.62) * 2.0)
    w_cold  = max(0.0, (0.40 - t_eff2) * 2.2)

    w_rain  = max(0.0, (m*1.15 + f*0.25) - 0.78)
    w_snow  = max(0.0, (m*1.05 + (0.45 - t_eff2) + h*0.4) - 0.55)

    rain_boost = 0.6 + 1.6 * precip_field
    snow_boost = 0.6 + 1.6 * precip_field
    fog_boost  = 0.6 + 1.6 * fog_field
    storm_boost= 0.5 + 1.8 * storm_field

    w_rain  *= rain_boost
    w_snow  *= snow_boost
    w_fog   *= fog_boost
    w_storm *= storm_boost

    if w_cold > 0:
        w_snow  += w_cold * 0.7
        w_fog   += w_cold * 0.2
        w_clear += w_cold * 0.1
        w_heat  *= 0.35

    w_heat = min(w_heat, w_clear + w_rain + 0.4)

    wetness = max(w_rain, w_snow, w_storm)
    w_clear *= 0.75 + 0.25 * (1.0 - _clamp(wetness, 0.0, 1.0))

    weights = {
        "clear": w_clear,
        "fog":   w_fog,
        "wind":  w_wind,
        "storm": w_storm,
        "rain":  w_rain,
        "snow":  w_snow,
        "heat":  w_heat,
    }

    rnd = random.Random(_seed_from(climate, now_bucket))
    total = sum(max(0.0,w) for w in weights.values())
    if total <= 1e-6:
        key_choice = "clear"
    else:
        r = rnd.random() * total
        acc = 0.0
        key_choice = "clear"
        for k, w in weights.items():
            w = max(0.0, w)
            if r <= acc + w:
                key_choice = k; break
            acc += w

    speed_mul   = 1.0
    fatigue_mul = 1.0
    precip      = "none"
    notes       = []

    if key_choice == "rain":
        speed_mul   *= 0.92
        fatigue_mul *= 1.20
        precip = "rain"
    elif key_choice == "snow":
        speed_mul   *= 0.78
        fatigue_mul *= 1.18
        precip = "snow"
    elif key_choice == "storm":
        speed_mul   *= 0.84
        fatigue_mul *= 1.28
        notes.append("сильный ветер/ливень")
    elif key_choice == "fog":
        speed_mul   *= 0.97
        notes.append("видимость ниже")
    elif key_choice == "heat":
        speed_mul   *= 0.95
        fatigue_mul *= 1.32

    out = {
        "ok": True,
        "key": key_choice,
        "name": key_choice,
        "speed_mul": round(speed_mul, 3),
        "fatigue_mul": round(fatigue_mul, 3),
        "precip": precip,
        "notes": "; ".join(notes) if notes else "",
        "fields": {
            "precip": round(precip_field, 3),
            "storm":  round(storm_field, 3),
            "fog":    round(fog_field, 3),
            "tanom":  round(temp_anom, 3),
        }
    }

    _cache_put(key, out)
    return dict(out)
