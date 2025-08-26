# world_biome_evolver.py
from __future__ import annotations
from typing import Dict
import math
from world_tuning import bucket_seconds

_NON_BIOME = {"road", "town", "tavern", "camp", "lava", "water"}
_SKINNABLE_SNOW = {"grass","meadow","forest","swamp","sand","desert","rock","road"}

def _clamp(v, a, b): return a if v < a else b if v > b else v
def _snow_skin(base: str) -> str: return f"{base}_snow" if base in _SKINNABLE_SNOW else "snow"

# --- hash / value-noise -------------------------------------------------------
def _h32(x: int) -> int:
    x ^= x >> 16; x *= 0x7feb352d; x &= 0xffffffff
    x ^= x >> 15; x *= 0x846ca68b; x &= 0xffffffff
    x ^= x >> 16; return x

def _vh(x: int, y: int, slot: int, salt: int = 0) -> float:
    h = _h32((x*73856093) ^ (y*19349663) ^ (slot*83492791) ^ (salt*374761393))
    return (h & 0xffffff) / float(1 << 24)

def _fade(t: float) -> float:  # 6t^5 - 15t^4 + 10t^3
    return ((6*t - 15)*t + 10)*t*t*t

def _lerp(a: float, b: float, t: float) -> float: return a + (b - a) * t

def _value_noise2(x: float, y: float, slot: int, freq: float, salt: int) -> float:
    X = x * freq; Y = y * freq
    xi = math.floor(X); yi = math.floor(Y)
    xf = X - xi;        yf = Y - yi
    u = _fade(_clamp(xf, 0.0, 1.0)); v = _fade(_clamp(yf, 0.0, 1.0))
    a = _vh(xi,     yi,     slot, salt)
    b = _vh(xi + 1, yi,     slot, salt)
    c = _vh(xi,     yi + 1, slot, salt)
    d = _vh(xi + 1, yi + 1, slot, salt)
    return _lerp(_lerp(a, b, u), _lerp(c, d, u), v)

def _blob_noise_static(x: int, y: int, slot: int) -> float:
    n1 = _value_noise2(x, y, slot, 0.14, 11)
    n2 = _value_noise2(x, y, slot, 0.33, 29)
    n  = 0.72*n1 + 0.28*n2
    nb = (
        n +
        0.18*_value_noise2(x+1, y,   slot, 0.14, 11) +
        0.18*_value_noise2(x-1, y,   slot, 0.14, 11) +
        0.18*_value_noise2(x,   y+1, slot, 0.14, 11) +
        0.18*_value_noise2(x,   y-1, slot, 0.14, 11)
    ) / (1.0 + 4*0.18)
    return _clamp(nb, 0.0, 1.0)

def _blob_noise_temporal(x: int, y: int, slot: int, phase: float) -> float:
    """Плавная интерполяция поля между slot и slot+1 по фазе 0..1 (миграция пятен)."""
    s = _clamp(phase, 0.0, 1.0)
    a = _blob_noise_static(x, y, slot)
    b = _blob_noise_static(x, y, slot+1)
    return _lerp(a, b, _fade(s))

# ------------------------------------------------------------------------------
def evolve_tile_ephemeral(base_tile: str,
                          x: int, y: int,
                          climate: Dict[str, float],
                          weather: Dict[str, object],
                          now_bucket: float,
                          now_phase: float = 0.0) -> str:
    """Возвращает тайл «сейчас». Снег — скин <base>_snow, пятна мигрируют плавно во времени."""
    if not base_tile or base_tile in _NON_BIOME:
        return base_tile

    # климат
    t = float(climate.get("temp", 0.5))
    m = float(climate.get("moist", 0.5))
    h = float(climate.get("height_mean", 0.5))
    f = float(climate.get("forest_density", 0.0))

    # погода
    key    = (weather or {}).get("key", "clear")
    precip = (weather or {}).get("precip", "none")

    # холодает на высоте и в лесу
    t_eff = _clamp(t - 0.35*h - 0.06*f, 0.0, 1.0)

    slot = int(now_bucket // bucket_seconds())
    blob = _blob_noise_temporal(x, y, slot, now_phase)  # связное поле с временной плавностью

    # --- снег (скин базового тайла) ---
    cold_push = max(0.0, (0.44 - t_eff) * 2.2) + (0.25 if (precip == "snow" or key == "snow") else 0.0) + (0.18 * h)
    if base_tile == "rock":   cold_push *= 0.85
    elif base_tile == "forest": cold_push *= 1.08

    snow_p = _clamp((cold_push - 0.52) * 1.9, 0.0, 1.0)
    # сгладим порог, чтобы «кромка» меньше дрожала
    snow_p = _fade(snow_p)
    if snow_p > 0 and blob < snow_p:
        return _snow_skin(base_tile)

    # --- болото (тоже использует мигрирующее поле) ---
    wet_push = m + (0.18 if precip == "rain" else 0.0) + (0.20 if key == "storm" else 0.0) - (0.10 if key == "heat" else 0.0)
    wet_push += 0.06 * f
    if base_tile in ("grass", "meadow", "forest"):
        swamp_p = _clamp((wet_push - 0.80) * 2.2, 0.0, 1.0)
        # немного псевдоспектрального смешивания двух шумов, тоже сгладим
        swamp_blob = _clamp(0.65*blob + 0.35*_blob_noise_temporal(x+7, y-5, slot, now_phase), 0.0, 1.0)
        swamp_p = _fade(swamp_p)
        if swamp_p > 0 and swamp_blob < swamp_p and t_eff > 0.28:
            return "swamp"

    # --- редкая сухость -> песок ---
    dry_push = (1.0 - m) + (0.20 if key == "heat" else 0.0)
    if base_tile in ("meadow", "grass") and dry_push > 1.10 and t_eff > 0.66:
        if blob > 0.88:   # очень редкие «языки» сухости
            return "sand"

    return base_tile
