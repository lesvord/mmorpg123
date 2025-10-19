# world_gen.py
import math, hashlib
from typing import List, Tuple, Dict
from world_tiles import *

# Глобальный сид — единый мир для всех
GLOBAL_SEED = int(hashlib.sha256(b"PocketKingdom:GLOBAL_WORLD_V2").hexdigest()[:12], 16) & 0x7fffffff

def _h32(x: int) -> int:
    x ^= (x >> 16); x = (x * 0x45d9f3b) & 0xFFFFFFFF
    x ^= (x >> 16); x = (x * 0x45d9f3b) & 0xFFFFFFFF
    x ^= (x >> 16); return x

def _hash2(x: int, y: int, seed: int) -> float:
    return ((_h32(x + seed*7349) ^ _h32(y + seed*9151)) & 0xFFFFFFFF) / 0xFFFFFFFF

def _mix(a,b,t): return a*(1-t)+b*t

def _noise2(x: float, y: float, seed: int) -> float:
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    def grd(ix,iy): return _hash2(ix,iy,seed)
    n00 = grd(xi, yi);     n10 = grd(xi+1, yi)
    n01 = grd(xi, yi+1);   n11 = grd(xi+1, yi+1)
    u = xf*xf*(3-2*xf); v = yf*yf*(3-2*yf)
    return _mix(_mix(n00,n10,u), _mix(n01,n11,u), v)

def _fbm(x: float, y: float, seed: int, octaves: int = 4, lacun: float = 2.0, gain: float = 0.5) -> float:
    amp = 1.0
    freq = 1.0
    s = 0.0
    norm = 0.0
    for _ in range(octaves):
        s += amp * _noise2(x * freq, y * freq, seed)
        norm += amp
        amp *= gain
        freq *= lacun
    return s / norm if norm > 0 else 0.0

def _pick_tile_by_env(h: float, m: float, t: float, *, latitude: float = 0.5) -> str:
    """Более "реалистичный" подбор биома с учётом широты."""

    # Реки / побережья
    if h < 0.30:
        return T_WATER
    if h < 0.34:
        return T_SAND

    # Высокогорье и широта → снеговые шапки/тундра
    cold_bias = (1.0 - t) * 0.4 + max(0.0, latitude - 0.65) * 0.9
    if h > 0.82 and cold_bias > 0.35:
        return T_SNOW
    if h > 0.78:
        return T_ROCK

    # Болота / поймы рек
    if m > 0.72 and h < 0.60:
        return T_SWAMP

    # Широты с низкой влажностью → пустыни/полупустыни
    arid_score = (0.65 - m) * 1.4 + (t - 0.55) * 0.8 + max(0.0, 0.45 - latitude) * 0.6
    if arid_score > 0.65 and 0.36 <= h <= 0.70:
        return T_DESERT if t > 0.55 else T_SAND

    # Поля/луга на среднем уровне
    if 0.40 <= h < 0.74:
        if m > 0.62:
            return T_FOREST
        if m > 0.48:
            return T_MEADOW
        return T_GRASS

    # Умеренно высокие холмы — каменистая местность
    if 0.74 <= h <= 0.82:
        return T_ROCK

    # Остаток — травянистая равнина с лёгкими снежными эффектами на севере
    if cold_bias > 0.55:
        return T_SNOW
    return T_GRASS


def _env(x: int, y: int) -> Dict[str,float]:
    s = GLOBAL_SEED
    # latitude в диапазоне 0..1 (0 — юг/экватор, 1 — север/полюс)
    lat = _fbm(0, y / 480.0, s + 997, octaves=2, gain=0.8)
    lat = min(1.0, max(0.0, 0.5 + (y / 4096.0) * 0.35 + (lat - 0.5) * 0.25))

    h = _fbm(x / 22.0, y / 22.0, s + 11, octaves=5)
    m = _fbm(x / 31.0, y / 31.0, s + 73, octaves=4)

    # Температура: базовый шум + широта + высота
    t_noise = _fbm(x / 27.0, y / 27.0, s + 149, octaves=4)
    t = t_noise
    t -= (h - 0.5) * 0.55  # чем выше — тем холоднее
    t -= (lat - 0.5) * 0.9
    t = min(1.0, max(0.0, t))

    fertility = _fbm(x / 18.0, y / 18.0, s + 281, octaves=3)
    fertility = min(1.0, max(0.0, fertility))

    return {"h": h, "m": m, "t": t, "lat": lat, "fert": fertility}

def pick_tile(x: int, y: int) -> str:
    e = _env(x,y)
    return _pick_tile_by_env(e["h"], e["m"], e["t"], latitude=e.get("lat", 0.5))

def generate_chunk(cx: int, cy: int, size: int=32) -> Tuple[List[List[str]], Dict[str,float]]:
    tiles=[]; count=0
    hsum=0.0; msum=0.0; tsum=0.0; forests=0
    fert_sum=0.0; lat_sum=0.0
    ox, oy = cx*size, cy*size
    for j in range(size):
        row=[]
        for i in range(size):
            x, y = ox+i, oy+j
            e = _env(x,y)
            hsum += e["h"]; msum += e["m"]; tsum += e["t"]; fert_sum += e["fert"]; lat_sum += e["lat"]; count += 1
            t = _pick_tile_by_env(e["h"], e["m"], e["t"], latitude=e.get("lat", 0.5))
            if t==T_FOREST: forests += 1
            row.append(t)
        tiles.append(row)
    climate = {
        "height_mean": hsum/max(1,count),
        "moist": msum/max(1,count),
        "temp": tsum/max(1,count),
        "forest_density": forests/max(1,count),
        "fertility": fert_sum/max(1,count),
        "latitude": lat_sum/max(1,count)
    }
    return tiles, climate
