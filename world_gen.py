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

def _fbm(x: float, y: float, seed: int, octaves: int=4, lacun: float=2.0, gain: float=0.5) -> float:
    amp=1.0; freq=1.0; s=0.0; norm=0.0
    for _ in range(octaves):
        s += amp * _noise2(x*freq, y*freq, seed)
        norm += amp
        amp *= gain; freq *= lacun
    return s/norm if norm>0 else 0.0

def _pick_tile_by_env(h: float, m: float, t: float) -> str:
    # Вода/песок — как было
    if h < 0.34: 
        return T_WATER
    if h < 0.38: 
        return T_SAND

    # Пустыня — как было
    if m < 0.25 and 0.38 <= h < 0.70 and t > 0.55:
        return T_DESERT

    # БОЛОТА: порог влажности ниже, допустимая высота выше
    if m > 0.70 and h < 0.60:
        return T_SWAMP

    # Средние высоты: распределяем лес/луг/трава по влажности
    if 0.44 <= h < 0.76:
        return T_FOREST if m > 0.60 else (T_MEADOW if m > 0.45 else T_GRASS)

    # ГОРЫ: начинаем раньше; снега — тоже чуть больше
    if h >= 0.76:
        if h > 0.88:
            return T_SNOW
        return T_ROCK

    # Остальное — трава
    return T_GRASS


def _env(x: int, y: int) -> Dict[str,float]:
    s = GLOBAL_SEED
    h = _fbm(x/22.0, y/22.0, s+11,  octaves=5)  # height
    m = _fbm(x/31.0, y/31.0, s+73,  octaves=4)  # moisture
    t = _fbm(x/27.0, y/27.0, s+149, octaves=4)  # temperature
    return {"h":h, "m":m, "t":t}

def pick_tile(x: int, y: int) -> str:
    e = _env(x,y)
    return _pick_tile_by_env(e["h"], e["m"], e["t"])

def generate_chunk(cx: int, cy: int, size: int=32) -> Tuple[List[List[str]], Dict[str,float]]:
    tiles=[]; count=0
    hsum=0.0; msum=0.0; tsum=0.0; forests=0
    ox, oy = cx*size, cy*size
    for j in range(size):
        row=[]
        for i in range(size):
            x, y = ox+i, oy+j
            e = _env(x,y); hsum += e["h"]; msum += e["m"]; tsum += e["t"]; count += 1
            t = _pick_tile_by_env(e["h"], e["m"], e["t"])
            if t==T_FOREST: forests += 1
            row.append(t)
        tiles.append(row)
    climate = {
        "height_mean": hsum/max(1,count),
        "moist": msum/max(1,count),
        "temp": tsum/max(1,count),
        "forest_density": forests/max(1,count)
    }
    return tiles, climate
