import json, time, math
from typing import Dict, List, Tuple, Any
from models import db
from world_models import WorldChunk, WorldBuilding
from world_weather import pick_weather_for_chunk

CHUNK_SIZE = 32

# эволюционируем чанк не чаще этого интервала (сек)
# было 60.0 — сделаем медленнее
EVO_INTERVAL = 600.0  # раз в 10 минут

# пороги/скорости накопления
SNOW_GROW   = 0.12   # при снегопаде
SNOW_COLD   = 0.04   # при стабильно низкой t
SNOW_MELT   = 0.08   # обычная оттепель
SNOW_HOT    = 0.12   # при жаре

WET_RAIN    = 0.10   # дождь/шторм накапливает «мокроту»
WET_DECAY   = 0.05   # высыхание без дождей
WET_MOIST_B = 0.02   # очень влажный климат слегка поддерживает мокроту
WET_DRY_B   = 0.01

FOREST_GROW = 0.03   # рост леса при сносной погоде и влажности
FOREST_BURN = 0.04   # усыхание/редение при жаре и засухе

# утилиты
def _clamp(v, a, b): return max(a, min(b, v))

def _h2u(x: int, y: int) -> float:
    """Детерминированная «случайность» 0..1 для клетки — чтоб рябь была стабильной, а не мерцала."""
    h = ((x * 73856093) ^ (y * 19349663)) & 0xffffffff
    return (h / 4294967295.0)

def _load_tiles(row: WorldChunk) -> List[List[str]]:
    return json.loads(row.tiles_json or "[]")

def _save_tiles(row: WorldChunk, tiles: List[List[str]]) -> None:
    row.tiles_json = json.dumps(tiles, separators=(",", ":"))

def _load_climate(row: WorldChunk) -> Dict[str, Any]:
    try:
        return json.loads(row.climate_json or "{}")
    except Exception:
        return {}

def _save_climate(row: WorldChunk, c: Dict[str, Any]) -> None:
    row.climate_json = json.dumps(c, separators=(",", ":"))

def _chunk_bounds(cx: int, cy: int) -> Tuple[int,int,int,int]:
    ox, oy = cx * CHUNK_SIZE, cy * CHUNK_SIZE
    return ox, oy, ox + CHUNK_SIZE - 1, oy + CHUNK_SIZE - 1

def _urbanization_in_chunk(cx: int, cy: int) -> float:
    x0, y0, x1, y1 = _chunk_bounds(cx, cy)
    area = CHUNK_SIZE * CHUNK_SIZE
    cnt = WorldBuilding.query.filter(
        WorldBuilding.x >= x0, WorldBuilding.x <= x1,
        WorldBuilding.y >= y0, WorldBuilding.y <= y1
    ).count()
    return _clamp(cnt / max(1, area), 0.0, 1.0)

def _ensure_base_tiles(cdict: Dict[str, Any], tiles: List[List[str]]) -> None:
    if "eco_base_tiles" not in cdict:
        # храним базу прямо в climate_json — без миграций
        cdict["eco_base_tiles"] = tiles  # это список списков строк — ок

def _eco_state(cdict: Dict[str, Any]) -> Dict[str, Any]:
    eco = cdict.get("eco") or {}
    eco.setdefault("last_ts", 0.0)
    eco.setdefault("snow", 0.0)    # 0..1 — «снежность»
    eco.setdefault("wet", 0.0)     # 0..1 — «мокрота/сырость»
    eco.setdefault("forest", 0.5)  # 0..1 — «давление леса»
    cdict["eco"] = eco
    return eco

def evolve_chunk(cx: int, cy: int, now: float | None = None) -> bool:
    """
    Эволюционирует 1 чанк. Возвращает True, если тайлы изменились.
    Работает аккуратно: не чаще EVO_INTERVAL; без миграций БД.
    ВАЖНО: не коммитит сама — оставляем один commit на весь тик выше по стеку.
    """
    if now is None:
        now = time.time()
    row = WorldChunk.query.filter_by(cx=cx, cy=cy).first()
    if not row:
        return False

    cdict = _load_climate(row)
    eco   = _eco_state(cdict)
    if now - float(eco.get("last_ts", 0.0)) < EVO_INTERVAL:
        return False

    tiles = _load_tiles(row)
    if not tiles or not tiles[0]:
        return False

    _ensure_base_tiles(cdict, tiles)
    base_tiles: List[List[str]] = cdict["eco_base_tiles"]

    # локальный климат чанка
    height_mean = float(cdict.get("height_mean", 0.5))
    moist       = float(cdict.get("moist", 0.5))
    temp        = float(cdict.get("temp", 0.5))
    forest_d    = float(cdict.get("forest_density", 0.3))

    # локальная погода: привязываем к длинным «слотам»
    now_bucket = math.floor(now / 1800.0) * 1800.0
    urb = _urbanization_in_chunk(cx, cy)
    w   = pick_weather_for_chunk(cdict, urb, now_bucket, cx=cx, cy=cy, now_ts=now)
    wkey = (w.get("key") or w.get("name") or "clear")

    # --- аккумулируем экосостояние ---
    snow = float(eco.get("snow", 0.0))
    wet  = float(eco.get("wet", 0.0))
    frs  = float(eco.get("forest", 0.5))

    # снег
    if wkey == "snow":
        snow += SNOW_GROW
    elif temp < 0.35:
        snow += SNOW_COLD
    elif wkey == "heat":
        snow -= SNOW_HOT
    else:
        snow -= SNOW_MELT
    snow = _clamp(snow, 0.0, 1.0)

    # мокрота (болота)
    if wkey in ("rain", "storm"):
        wet += WET_RAIN
    else:
        wet -= WET_DECAY
    if moist > 0.72:
        wet += WET_MOIST_B
    elif moist < 0.35:
        wet -= WET_DRY_B
    wet = _clamp(wet, 0.0, 1.0)

    # лес
    if moist > 0.58 and wkey not in ("heat", "storm"):
        frs += FOREST_GROW
    if wkey == "heat" and moist < 0.40:
        frs -= FOREST_BURN
    frs = _clamp(frs, 0.0, 1.0)

    # --- конверсия тайлов ---
    changed = False
    h_lo = height_mean < 0.60
    allow_swamp = h_lo and wet > 0.45

    H = len(tiles)
    W = len(tiles[0])

    # пороги
    snow_full = snow > 0.66
    snow_mix  = 0.33 < snow <= 0.66
    swamp_full_t = 0.75
    swamp_mix_t  = 0.55

    forest_full_t = 0.70
    forest_mix_t  = 0.55
    forest_decay_t = 0.30

    for j in range(H):
        for i in range(W):
            x = cx * CHUNK_SIZE + i
            y = cy * CHUNK_SIZE + j

            base = base_tiles[j][i]
            cur  = tiles[j][i]
            u    = _h2u(x, y)

            # 1) Снег
            if base not in ("water", "lava", "town", "road", "tavern", "camp"):
                if snow_full:
                    if cur != "snow":
                        tiles[j][i] = "snow"; changed = True
                elif snow_mix:
                    p = (snow - 0.33) / 0.33  # 0..1
                    want_snow = u < p
                    if want_snow and cur != "snow":
                        tiles[j][i] = "snow"; changed = True
                    if not want_snow and cur == "snow":
                        if cur != base:
                            tiles[j][i] = base; changed = True
                else:
                    if cur == "snow":
                        tiles[j][i] = base; changed = True
            else:
                if cur == "snow":
                    tiles[j][i] = base; changed = True

            # 2) Болота
            cur = tiles[j][i]
            if cur in ("water", "lava", "rock", "snow", "town", "road", "tavern", "camp"):
                pass
            else:
                if allow_swamp:
                    if wet >= swamp_full_t:
                        if cur != "swamp":
                            tiles[j][i] = "swamp"; changed = True
                    elif wet >= swamp_mix_t:
                        p = (wet - swamp_mix_t) / (1.0 - swamp_mix_t)  # 0..1
                        if u < p and cur != "swamp":
                            tiles[j][i] = "swamp"; changed = True
                        if u >= p and cur == "swamp":
                            tiles[j][i] = base; changed = True
                    else:
                        if cur == "swamp":
                            tiles[j][i] = base; changed = True
                else:
                    if cur == "swamp":
                        tiles[j][i] = base; changed = True

            # 3) Лес
            cur = tiles[j][i]
            if cur in ("water", "lava", "snow", "rock", "town", "road", "tavern", "camp"):
                continue

            if frs >= forest_full_t:
                if base in ("grass", "meadow") and cur != "forest":
                    tiles[j][i] = "forest"; changed = True
            elif frs >= forest_mix_t:
                if base in ("grass", "meadow") and cur != "forest":
                    p = (frs - forest_mix_t) / (forest_full_t - forest_mix_t)
                    if u < p:
                        tiles[j][i] = "forest"; changed = True
            else:
                if cur == "forest" and frs < forest_decay_t:
                    tiles[j][i] = "meadow" if base == "meadow" else "grass"
                    changed = True

    # сохранить экосостояние; НЕ коммитим тут — пусть внешний код коммитит тик целиком
    eco["snow"], eco["wet"], eco["forest"] = float(snow), float(wet), float(frs)
    eco["last_ts"] = float(now)
    _save_climate(row, cdict)

    if changed:
        _save_tiles(row, tiles)

    db.session.add(row)
    db.session.flush()  # вместо commit()

    return changed

def evolve_ring(cxc: int, cyc: int, radius: int = 1, now: float | None = None) -> int:
    changed = 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if evolve_chunk(cxc + dx, cyc + dy, now=now):
                changed += 1
    return changed

def evolve_visible_area(center_x: int, center_y: int, now: float | None = None) -> int:
    cxc = math.floor(center_x / CHUNK_SIZE) if center_x >= 0 else -math.ceil(abs(center_x) / CHUNK_SIZE)
    cyc = math.floor(center_y / CHUNK_SIZE) if center_y >= 0 else -math.ceil(abs(center_y) / CHUNK_SIZE)
    return evolve_ring(cxc, cyc, radius=1, now=now)
