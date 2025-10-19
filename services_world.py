import time, json, heapq, math
from dataclasses import dataclass, field
from typing import Dict, Any, List, Tuple, Optional

from sqlalchemy.exc import IntegrityError

from models import db
from world_models import ensure_world_models, WorldState, WorldChunk, WorldBuilding, WorldOverride
from world_tiles import *  # константы тайлов + is_passable, tile_speed, tile_fatigue_mul, tile_rest_mul, tile_env_fatigue_mul
import world_tiles as W     # публичные утилиты для UI: env_levels, и доступ к тем же функциям
from world_gen import generate_chunk
from world_weather import pick_weather_for_chunk
from world_biome_evolver import evolve_tile_ephemeral  # ЭФЕМЕРНАЯ смена биомов (снег/болото/сухость)
from world_biome_persist import evolve_chunk_persistent  # ПЕРМАНЕНТНАЯ эволюция биомов
from world_tuning import (
    bucket_seconds,
    evolve_min_period_seconds,
    prefetch_cooldown_seconds,
)
from accounts.models import inventory_totals


# ==================== ВСПОМОГАТЕЛЬНОЕ ====================

def _now() -> float:
    return time.time()

def _clamp(v, a, b):
    return max(a, min(b, v))

def _uid(user_or_id) -> int:
    """
    Унификация входного идентификатора пользователя:
    - werkzeug.local.LocalProxy -> разворачиваем
    - ORM-объект с .id / .user_id / .uid / .tg_id / .telegram_id / .pk
    - dict с ключом id / user_id / uid / tg_id / telegram_id / pk
    - str/int/float
    - запасной путь: любой атрибут, имя которого содержит "id"
    """
    if user_or_id is None:
        raise TypeError("Cannot extract user id from None")

    # 1) LocalProxy -> unwrap
    try:
        from werkzeug.local import LocalProxy
        if isinstance(user_or_id, LocalProxy):
            user_or_id = user_or_id._get_current_object()
    except Exception:
        pass

    # 2) Примитивы
    if isinstance(user_or_id, (int, float)):
        return int(user_or_id)
    if isinstance(user_or_id, str):
        s = user_or_id.strip()
        # на случай если строка типа "User(id=123)" — вытащим цифры справа
        try:
            return int(s)
        except Exception:
            import re
            m = re.search(r'(\d+)', s)
            if m:
                return int(m.group(1))

    # 3) dict
    if isinstance(user_or_id, dict):
        for k in ("id", "user_id", "uid", "tg_id", "telegram_id", "pk"):
            if k in user_or_id and user_or_id[k] is not None:
                try:
                    return int(user_or_id[k])
                except Exception:
                    pass

    # 4) ORM-объект: известные атрибуты
    for attr in ("id", "user_id", "uid", "tg_id", "telegram_id", "pk"):
        try:
            if hasattr(user_or_id, attr):
                val = getattr(user_or_id, attr)
                # если это callable-свойство — попробуем вызвать
                if callable(val):
                    val = val()
                if val is not None:
                    return int(val)
        except Exception:
            pass

    # 5) Фолбэк: любой attr с "id" в названии
    try:
        for name in dir(user_or_id):
            if "id" in name.lower():
                try:
                    val = getattr(user_or_id, name)
                    if callable(val):
                        val = val()
                    if val is not None:
                        return int(val)
                except Exception:
                    continue
    except Exception:
        pass

    raise TypeError(f"Cannot extract user id from {type(user_or_id).__name__}")


CHUNK_SIZE = 32

# === Новая модель движения / энергетика ===
_BASE_FATIGUE_PER_TILE = 0.22
_FATIGUE_EFF_PENALTY   = 0.33

# Восстановление при отдыхе
_BASE_REST_PER_SEC     = 0.030

# Реген во время движения
_MOVE_REST_PER_SEC     = 0.012

# Насколько сильно погода влияет на усталость (1.0 = старое значение)
_WEATHER_FATIGUE_STRENGTH = 1.35

# Визуальная дискретизация миграции пятен (отображение патча)
_VIEW_PHASE_STEPS = 2

# Ограничение частоты перманентной эволюции для одного чанка (подчиняется ускорению)
_EVOLVE_MIN_PERIOD_SEC = evolve_min_period_seconds()


# — окно видимой области и запас подрисовки —
_VIEW_W = 15
_VIEW_H = 9
_PAD_X  = 8    # слева и справа
_PAD_Y  = 5    # сверху и снизу
_PATCH_W = _VIEW_W + _PAD_X*2  # 31
_PATCH_H = _VIEW_H + _PAD_Y*2  # 19


# ==================== КОНТЕКСТ / КЕШИ ====================

@dataclass
class _TileCtx:
    now_bucket: float
    influence: float
    bmap: Dict[Tuple[int, int], str]  # (x,y)->kind построек
    omap: Dict[Tuple[int, int], str]  # (x,y)->override.tile_id
    tiles_by_chunk: Dict[Tuple[int,int], List[List[str]]] = field(default_factory=dict)
    climate_by_chunk: Dict[Tuple[int,int], Dict[str,float]] = field(default_factory=dict)
    weather_by_chunk: Dict[Tuple[int,int], Dict[str,Any]] = field(default_factory=dict)


def _rect_overlay_maps(x0:int,y0:int,x1:int,y1:int):
    """Собирает все постройки/оверрайды в прямоугольнике единым запросом."""
    blds = WorldBuilding.query.filter(
        WorldBuilding.x >= x0, WorldBuilding.x <= x1,
        WorldBuilding.y >= y0, WorldBuilding.y <= y1
    ).all()
    ovrs = WorldOverride.query.filter(
        WorldOverride.x >= x0, WorldOverride.x <= x1,
        WorldOverride.y >= y0, WorldOverride.y <= y1
    ).all()
    bmap = {(b.x,b.y): b.kind for b in blds}
    omap = {(o.x,o.y): o.tile_id for o in ovrs}
    return bmap, omap


def _get_chunk(cx:int, cy:int) -> Optional[WorldChunk]:
    return WorldChunk.query.filter_by(cx=cx, cy=cy).first()

def _ensure_chunk(cx:int, cy:int) -> WorldChunk:
    """Идёмпотентное создание чанка с защитой от гонки вставки."""
    row = _get_chunk(cx, cy)
    if row:
        return row

    tiles, climate = generate_chunk(cx, cy, CHUNK_SIZE)
    row = WorldChunk(
        cx=cx, cy=cy, size=CHUNK_SIZE,
        tiles_json=json.dumps(tiles, separators=(",", ":")),
        climate_json=json.dumps(climate, separators=(",", ":")),
        created_at=_now()
    )
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        row = _get_chunk(cx, cy)
        if not row:
            row = WorldChunk(
                cx=cx, cy=cy, size=CHUNK_SIZE,
                tiles_json=json.dumps(tiles, separators=(",", ":")),
                climate_json=json.dumps(climate, separators=(",", ":")),
                created_at=_now()
            )
            db.session.add(row); db.session.commit()
    return row


# ---- L2 TTL-кеш на процесс ----
_TILE_CACHE: Dict[Tuple[int,int], Tuple[float, List[List[str]]]] = {}
_CLIMATE_CACHE: Dict[Tuple[int,int], Tuple[float, Dict[str,float]]] = {}
_CACHE_TTL = 15.0

def _invalidate_chunk_cache(cx:int, cy:int):
    """Сбрасываем кэши, если чанк реально мутировал, чтобы сразу увидеть изменения."""
    _TILE_CACHE.pop((cx, cy), None)
    # климат мы не меняем при перманентной эволюции — обычно не трогаем:
    # _CLIMATE_CACHE.pop((cx, cy), None)

def _tiles_of(cx:int, cy:int) -> List[List[str]]:
    now = _now()
    key = (cx,cy)
    ts, val = _TILE_CACHE.get(key, (0.0, None))
    if val is not None and now - ts < _CACHE_TTL:
        return val
    row = _ensure_chunk(cx,cy)
    tiles = json.loads(row.tiles_json or "[]")
    _TILE_CACHE[key] = (now, tiles)
    return tiles

def _climate_of(cx:int, cy:int) -> Dict[str,float]:
    now = _now()
    key = (cx,cy)
    ts, val = _CLIMATE_CACHE.get(key, (0.0, None))
    if val is not None and now - ts < _CACHE_TTL:
        return val
    row = _ensure_chunk(cx, cy)
    try: climate = json.loads(row.climate_json or "{}")
    except Exception: climate = {}
    _CLIMATE_CACHE[key] = (now, climate)
    return climate

def _tiles_cached(ctx:_TileCtx, cx:int, cy:int):
    key=(cx,cy)
    t = ctx.tiles_by_chunk.get(key)
    if t is None:
        t = _tiles_of(cx, cy)
        ctx.tiles_by_chunk[key] = t
    return t

def _climate_cached(ctx:_TileCtx, cx:int, cy:int):
    key=(cx,cy)
    c = ctx.climate_by_chunk.get(key)
    if c is None:
        c = _climate_of(cx, cy)
        ctx.climate_by_chunk[key] = c
    return c

def _weather_for_chunk(ctx:_TileCtx, cx:int, cy:int):
    key=(cx,cy)
    w = ctx.weather_by_chunk.get(key)
    if w is None:
        clim = _climate_cached(ctx, cx, cy)
        # передаём координаты и текущее время для плавной интерполяции внутри погоды
        w = pick_weather_for_chunk(clim, ctx.influence, ctx.now_bucket, cx=cx, cy=cy, now_ts=_now())
        ctx.weather_by_chunk[key] = w
    return w


# -------------------- ПЕРМАНЕНТНАЯ ЭВОЛЮЦИЯ/ПРЕФЕТЧ --------------------

_PREFETCH_GUARD: Dict[Tuple[int,int], float] = {}
_PREFETCH_COOLDOWN = prefetch_cooldown_seconds()

def _maybe_evolve_chunk(row: WorldChunk, influence: float = 0.0, now_ts: Optional[float] = None, *, autocommit: bool = True):
    """
    Обновляет перманентную эволюцию для чанка, если пришло время.
    НЕ трогаем last_evolve_ts до вызова evolve_chunk_persistent!
    """
    if not row:
        return
    now_ts = float(now_ts or _now())
    last = float(getattr(row, "last_evolve_ts", 0.0) or 0.0)
    # частоту ограничиваем здесь, но метку времени НЕ выставляем
    from world_tuning import evolve_min_period_seconds
    if now_ts - last < evolve_min_period_seconds():
        return  # рано

    try:
        climate = json.loads(row.climate_json or "{}")
    except Exception:
        climate = {}

    now_bucket = math.floor(now_ts/1800.0)*1800.0  # ок, это только для погоды
    weather = pick_weather_for_chunk(climate, float(influence or 0.0), now_bucket, cx=row.cx, cy=row.cy, now_ts=now_ts)

    # evolve_chunk_persistent САМА обновит row.last_evolve_ts и eco_json/tiles_json при изменениях
    changed = evolve_chunk_persistent(row, climate, weather, now_ts)

    # если тайлы изменились — сбросим кэш по чанку (иначе UI может показывать старое до TTL)
    if changed:
        try:
            _TILE_CACHE.pop((row.cx, row.cy), None)
        except Exception:
            pass

    db.session.add(row)
    if autocommit:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


def _prefetch_ring(cx:int, cy:int, radius:int=1):
    now_ts = _now()
    key = (cx, cy)
    if now_ts - _PREFETCH_GUARD.get(key, 0.0) < _PREFETCH_COOLDOWN:
        return
    _PREFETCH_GUARD[key] = now_ts

    touched = False
    for dy in range(-radius, radius+1):
        for dx in range(-radius, radius+1):
            r = _ensure_chunk(cx+dx, cy+dy)
            _maybe_evolve_chunk(r, influence=0.0, now_ts=now_ts, autocommit=False)
            touched = True
    if touched:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()


# -------------------- TILE/BUILDING LOOKUPS --------------------

def _building_at(x:int,y:int) -> Optional[WorldBuilding]:
    return WorldBuilding.query.filter_by(x=x, y=y).first()

def _override_at(x:int,y:int) -> Optional[WorldOverride]:
    return WorldOverride.query.filter_by(x=x, y=y).first()

def _chunk_of_xy(x:int,y:int) -> Tuple[int,int,int,int]:
    cx = x // CHUNK_SIZE
    cy = y // CHUNK_SIZE
    ox, oy = cx*CHUNK_SIZE, cy*CHUNK_SIZE
    return cx, cy, ox, oy

def _parse_json(s: str) -> dict:
    try: return json.loads(s or "{}")
    except Exception: return {}


# -------------------- TILE RESOLVE (эпемерные скины) --------------------

def _tile_at(x: int, y: int, ctx: Optional[_TileCtx] = None, *, for_view: bool = False) -> str:
    """
    Базовый тайл с учётом построек/оверрайдов + ЭФЕМЕРНЫЕ живые биомы поверх (снег/болото/сухость).
    ctx=None      -> старый медленный путь (совместимость).
    for_view=True -> используем «квантованную» фазу миграции пятен (чтобы картинка не дёргалась).
    """
    # Быстрый путь: всё из заранее собранных карт и кешей
    if ctx is not None:
        ov = ctx.omap.get((x,y))
        if ov:
            return ov
        kind = ctx.bmap.get((x,y))
        if kind in (T_TOWN, T_CAMP, T_TAVERN, T_ROAD):
            return kind

        cx, cy, ox, oy = _chunk_of_xy(x,y)
        tiles = _tiles_cached(ctx, cx, cy)
        base = tiles[y-oy][x-ox]

        climate = _climate_cached(ctx, cx, cy)
        weather = _weather_for_chunk(ctx, cx, cy)

        # фаза
        now = _now()
        phase = (now - ctx.now_bucket) / 1800.0
        if for_view:
            step = max(1, int(_VIEW_PHASE_STEPS))
            phase = math.floor(phase * step) / step

        return evolve_tile_ephemeral(base, x, y, climate, weather, ctx.now_bucket, phase)

    # Медленный (совместимость)
    ov = _override_at(x,y)
    if ov: return ov.tile_id
    b = _building_at(x,y)
    if b and b.kind in (T_TOWN, T_CAMP, T_TAVERN, T_ROAD):
        return b.kind
    cx, cy, ox, oy = _chunk_of_xy(x,y)
    tiles = _tiles_of(cx,cy)
    base = tiles[y-oy][x-ox]
    climate = _climate_of(cx, cy)
    now = _now()
    _BUCKET = bucket_seconds()
    now_bucket = math.floor(now/_BUCKET)*_BUCKET

    phase = (now - now_bucket) / 1800.0
    if for_view:
        step = max(1, int(_VIEW_PHASE_STEPS))
        phase = math.floor(phase * step) / step
    weather = pick_weather_for_chunk(climate, 0.0, now_bucket, cx=cx, cy=cy, now_ts=now)
    return evolve_tile_ephemeral(base, x, y, climate, weather, now_bucket, phase)


# -------------------- Энергетика шага --------------------

def _weather_eff_pair(weather: dict) -> Tuple[float, float]:
    """
    Возвращает (w_eff, w_raw), где w_raw — множитель погоды из генератора,
    а w_eff — «усиленный» с учетом _WEATHER_FATIGUE_STRENGTH.
    """
    w_raw = float(weather.get("fatigue_mul", 1.0))
    w_eff = 1.0 + (w_raw - 1.0) * _WEATHER_FATIGUE_STRENGTH
    return w_eff, w_raw

def _energy_cost_estimate(tile: str, weather: dict) -> float:
    # (оставлено для совместимости/отладки)
    fat_mul  = tile_fatigue_mul(tile)
    w_raw    = float(weather.get("fatigue_mul", 1.0))
    w_mul    = 1.0 + (w_raw - 1.0) * _WEATHER_FATIGUE_STRENGTH
    return _BASE_FATIGUE_PER_TILE * fat_mul * w_mul

def _energy_cost_runtime(tile: str, weather: dict, fatigue: float) -> float:
    # (оставлено для совместимости/отладки)
    fat_mul  = tile_fatigue_mul(tile)
    w_raw    = float(weather.get("fatigue_mul", 1.0))
    w_mul    = 1.0 + (w_raw - 1.0) * _WEATHER_FATIGUE_STRENGTH
    eff_mul  = 1.0 + (max(0.0, fatigue)/100.0) * _FATIGUE_EFF_PENALTY
    return _BASE_FATIGUE_PER_TILE * fat_mul * w_mul * eff_mul


# -------------------- A* по энергозатратам --------------------

def _neighbors(x:int,y:int):
    yield (x+1,y); yield (x-1,y); yield (x,y+1); yield (x,y-1)

def _astar(row: WorldState, tx:int,ty:int, weather:dict, ctx: Optional[_TileCtx]=None, max_iter:int=100000) -> List[Tuple[int,int]]:
    sx,sy = int(row.pos_x), int(row.pos_y)
    if (sx,sy)==(tx,ty): return []

    openh=[]; heapq.heappush(openh,(0.0,(sx,sy)))
    came: Dict[Tuple[int,int], Tuple[int,int]]={}
    g: Dict[Tuple[int,int], float] = {(sx,sy):0.0}
    seen=set()

    avg = _BASE_FATIGUE_PER_TILE
    def h(x,y): return avg * (abs(x-tx)+abs(y-ty))

    it=0
    while openh and it<max_iter:
        it+=1
        _,(x,y)=heapq.heappop(openh)
        if (x,y) in seen: continue
        seen.add((x,y))

        if (x,y)==(tx,ty):
            path=[(x,y)]
            while (x,y)!=(sx,sy):
                x,y=came[(x,y)]
                path.append((x,y))
            path.reverse()
            if path and path[0]==(sx,sy): path=path[1:]
            return path

        for nx,ny in _neighbors(x,y):
            t = _tile_at(nx,ny, ctx=ctx, for_view=False)  # логика: точная фаза, но без лишних SQL
            if not is_passable(t):
                continue

            if ctx is not None:
                cxn = nx // CHUNK_SIZE
                cyn = ny // CHUNK_SIZE
                clim_n = _climate_cached(ctx, cxn, cyn)
                wch_n  = _weather_for_chunk(ctx, cxn, cyn)
            else:
                # совместимость: редкий путь без контекста
                cxn = nx // CHUNK_SIZE
                cyn = ny // CHUNK_SIZE
                clim_n = _climate_of(cxn, cyn)
                now = _now()
                now_bucket = math.floor(now/1800.0)*1800.0
                wch_n = pick_weather_for_chunk(clim_n, 0.0, now_bucket, cx=cxn, cy=cyn, now_ts=now)

            w_eff, _ = _weather_eff_pair(wch_n)
            env_mul = tile_env_fatigue_mul(t, clim_n, wch_n)
            base_mul = tile_fatigue_mul(t)
            c = _BASE_FATIGUE_PER_TILE * base_mul * env_mul * w_eff

            ng = g[(x,y)] + c
            if ng < g.get((nx,ny), 1e18):
                g[(nx,ny)] = ng
                came[(nx,ny)] = (x,y)
                f = ng + h(nx,ny)
                heapq.heappush(openh,(f,(nx,ny)))

    return []


# -------------------- USER STATE --------------------

def _get_state(uid_any) -> WorldState:
    """Берём/создаём строку состояния ИСКЛЮЧИТЕЛЬНО для этого пользователя."""
    uid_s = str(_uid(uid_any))
    row = WorldState.query.filter_by(user_id=uid_s).first()
    if row:
        return row
    row = WorldState(
        user_id=uid_s, pos_x=0, pos_y=0,
        dest_x=None, dest_y=None,
        path_json="[]",
        last_update=_now(),
        speed=1.6,
        fatigue=15.0,
        resting=False
    )
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        row = WorldState.query.filter_by(user_id=uid_s).first()
        if not row:
            row = WorldState(
                user_id=uid_s, pos_x=0, pos_y=0,
                dest_x=None, dest_y=None,
                path_json="[]",
                last_update=_now(),
                speed=1.6,
                fatigue=15.0,
                resting=False
            )
            db.session.add(row); db.session.commit()
    return row

def _step_time(row: WorldState) -> float:
    sp = float(row.speed or 1.6)
    sp = _clamp(sp, 0.2, 6.0)
    return 1.0 / sp


# -------------------- ENGINE: MOVE / REST --------------------

def _advance(row: WorldState):
    """
    Сдвигаем героя вперёд на прошедшее время.
    ВАЖНО: префетч/эволюцию чанков делаем снаружи (get_world_state), чтобы тик был быстрым.
    """
    path: List[Tuple[int,int]] = json.loads(row.path_json or "[]")

    now = _now()
    now_bucket = math.floor(now / 1800.0) * 1800.0

    cx = row.pos_x // CHUNK_SIZE
    cy = row.pos_y // CHUNK_SIZE
    climate = _climate_of(cx, cy)

    # влияние игроков (урбанизация)
    ox = row.pos_x - 10; oy = row.pos_y - 6
    ex = row.pos_x + 10; ey = row.pos_y + 6
    area = max(1, (ex - ox + 1) * (ey - oy + 1))
    cnt = WorldBuilding.query.filter(
        WorldBuilding.x >= ox, WorldBuilding.x <= ex,
        WorldBuilding.y >= oy, WorldBuilding.y <= ey
    ).count()
    influence = _clamp(cnt / area, 0.0, 1.0)
    weather = pick_weather_for_chunk(climate, influence, now_bucket, cx=cx, cy=cy, now_ts=now)

    dt = max(0.0, now - float(row.last_update or now))
    fatigue = float(row.fatigue or 0.0)

    try:
        inv_uid = int(float(row.user_id))
        load = inventory_totals(inv_uid)
    except Exception:
        load = {"speed_mul": 1.0, "fatigue_mul": 1.0}

    load_speed_mul = float(load.get("speed_mul") or 1.0)
    load_fatigue_mul = float(load.get("fatigue_mul") or 1.0)

    # Сформируем крошечный локальный контекст для текущей клетки и ближайшего шага пути
    if path:
        nx0, ny0 = path[0]
        rx0 = min(int(row.pos_x), nx0) - 1
        ry0 = min(int(row.pos_y), ny0) - 1
        rx1 = max(int(row.pos_x), nx0) + 1
        ry1 = max(int(row.pos_y), ny0) + 1
    else:
        rx0 = int(row.pos_x) - 1; ry0 = int(row.pos_y) - 1
        rx1 = int(row.pos_x) + 1; ry1 = int(row.pos_y) + 1
    bmap, omap = _rect_overlay_maps(rx0, ry0, rx1, ry1)
    local_ctx = _TileCtx(now_bucket=now_bucket, influence=influence, bmap=bmap, omap=omap)

    cur_tile = _tile_at(row.pos_x, row.pos_y, ctx=local_ctx, for_view=False)
    on_camp = (cur_tile == T_CAMP)
    standing_still = not path
    if on_camp and standing_still:
        row.resting = True

    # REST MODE
    if row.resting or not path:
        rest_mul = tile_rest_mul(cur_tile) * (1.0 / float(weather.get("fatigue_mul", 1.0)))
        camp_bonus = 1.15 if on_camp else 1.0
        fatigue = max(0.0, fatigue - _BASE_REST_PER_SEC * rest_mul * camp_bonus * dt)
        if row.resting and fatigue <= 20.0 and path:
            row.resting = False
        row.fatigue = fatigue
        row.last_update = now
        return

    # MOVE
    x, y = int(row.pos_x), int(row.pos_y)
    idx = 0
    left_dt = dt

    while left_dt > 0 and idx < len(path):
        tx, ty = path[idx]
        next_tile = _tile_at(tx, ty, ctx=local_ctx, for_view=False)
        if not is_passable(next_tile):
            path = []
            break

        cxn, cyn, _, _ = _chunk_of_xy(tx, ty)
        wch_next = _weather_for_chunk(local_ctx, cxn, cyn)
        w_speed_mul = float(wch_next.get("speed_mul") or 1.0)
        tile_speed_mul = tile_speed(next_tile)
        base_speed = float(row.speed or 1.6)
        eff_speed = max(0.12, base_speed * tile_speed_mul * w_speed_mul * load_speed_mul)
        step_t = 1.0 / eff_speed

        if left_dt >= step_t:
            time_spent = step_t
            x, y = tx, ty
            left_dt -= step_t
            idx += 1
        else:
            time_spent = left_dt
            left_dt = 0.0

        # расход за долю шага (учёт эко-мода и локальной погоды следующей клетки)
        clim_next = _climate_cached(local_ctx, cxn, cyn)
        w_eff, w_raw = _weather_eff_pair(wch_next)

        env_mul = tile_env_fatigue_mul(next_tile, clim_next, wch_next)
        base_mul = tile_fatigue_mul(next_tile)
        cost_full_tile = _BASE_FATIGUE_PER_TILE * base_mul * env_mul * w_eff * load_fatigue_mul

        fatigue += cost_full_tile * (time_spent / step_t)

        # реген во время движения (против сырого множителя погоды)
        rest_mul = tile_rest_mul(next_tile) * (1.0 / w_raw)
        fatigue = max(0.0, fatigue - _MOVE_REST_PER_SEC * rest_mul * time_spent)

        if fatigue >= 100.0:
            fatigue = 100.0
            path = []
            row.dest_x = row.dest_y = None
            row.resting = True
            break

    row.pos_x, row.pos_y = x, y
    rest = path[idx:]
    row.path_json = json.dumps(rest, separators=(",", ":"))
    if not rest:
        row.dest_x = row.dest_y = None

    row.last_update = now - left_dt
    row.fatigue = _clamp(fatigue, 0.0, 100.0)


# -------------------- VIEW / PATCH --------------------

def _buildings_rect(x0:int,y0:int,x1:int,y1:int) -> List[dict]:
    q = WorldBuilding.query.filter(
        WorldBuilding.x >= x0, WorldBuilding.x <= x1,
        WorldBuilding.y >= y0, WorldBuilding.y <= y1
    ).all()
    return [dict(id=b.id, x=b.x, y=b.y, kind=b.kind, owner_id=b.owner_id) for b in q]

def _player_influence(x0:int,y0:int,x1:int,y1:int) -> float:
    area = max(1, (x1-x0+1)*(y1-y0+1))
    cnt = WorldBuilding.query.filter(
        WorldBuilding.x >= x0, WorldBuilding.x <= x1,
        WorldBuilding.y >= y0, WorldBuilding.y <= y1
    ).count()
    return _clamp(cnt/area, 0.0, 1.0)

def _patch(cx:int, cy:int, w:int=_PATCH_W, h:int=_PATCH_H) -> Dict[str,Any]:
    """
    Возвращает:
      - видимую камеру 15×9 в полях: ox, oy, w, h, tiles
      - большой буфер 31×19 в поле buffer: {ox, oy, w, h, tiles}
      - служебные метаданные: center, pad
    """
    # --- большой буфер (31×19) ---
    big_ox = cx - w//2
    big_oy = cy - h//2
    x0, y0, x1, y1 = big_ox, big_oy, big_ox + w - 1, big_oy + h - 1

    infl = _player_influence(x0, y0, x1, y1)
    now = _now()
    now_bucket = math.floor(now/1800.0)*1800.0
    bmap, omap = _rect_overlay_maps(x0, y0, x1, y1)
    ctx = _TileCtx(now_bucket=now_bucket, influence=infl, bmap=bmap, omap=omap)

    buffer_tiles = []
    for j in range(h):
        row = []
        for i in range(w):
            row.append(_tile_at(big_ox + i, big_oy + j, ctx=ctx, for_view=True))
        buffer_tiles.append(row)

    blds = _buildings_rect(x0, y0, x1, y1)

    # --- видимое окно 15×9 (отрезаем из буфера) ---
    view_ox = cx - _VIEW_W // 2
    view_oy = cy - _VIEW_H // 2
    si = _PAD_X  # смещение внутри буфера по X
    sj = _PAD_Y  # смещение по Y
    visible_tiles = [buffer_tiles[sj + jj][si:si + _VIEW_W] for jj in range(_VIEW_H)]

    return {
        # видимая камера (как раньше ожидал фронт)
        "ox": view_ox, "oy": view_oy, "w": _VIEW_W, "h": _VIEW_H,
        "tiles": visible_tiles,
        "buildings": blds,

        # большой буфер для подрисовки вперёд
        "buffer": {"ox": big_ox, "oy": big_oy, "w": w, "h": h, "tiles": buffer_tiles},

        # метаданные
        "center": {"i": _VIEW_W // 2, "j": _VIEW_H // 2, "x": cx, "y": cy},
        "pad": {"x": _PAD_X, "y": _PAD_Y},
    }


# ------------- TEMP CAMP HELPERS -------------

def _temp_camp_here(row: WorldState) -> Optional[WorldBuilding]:
    b = _building_at(row.pos_x, row.pos_y)
    if not b or b.kind != "camp": return None
    dj = _parse_json(b.data_json)
    if not dj.get("temp"): return None
    if str(b.owner_id or "") != str(row.user_id): return None
    return b

def _remove_temp_camp_here(row: WorldState):
    b = _temp_camp_here(row)
    if b:
        db.session.delete(b)
        db.session.commit()


# -------------------- PUBLIC API --------------------

def get_world_state(user_or_id) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    db.session.add(row); db.session.commit()

    # эволюция/префетч ближайших чанков — СЮДА (а не в _advance), чтобы тик был быстрым.
    _prefetch_ring(row.pos_x//CHUNK_SIZE, row.pos_y//CHUNK_SIZE, radius=1)

    # сразу строим патч (он уже содержит согласованные погоду/фазу/эфемерные скины)
    pt = _patch(row.pos_x, row.pos_y)
    pt["view"] = {"ox": pt["ox"], "oy": pt["oy"], "w": pt["w"], "h": pt["h"]}

    # влияние и актуальная погода для UI-цифр
    infl = _player_influence(pt["ox"], pt["oy"], pt["ox"]+pt["w"]-1, pt["oy"]+pt["h"]-1)

    cx, cy = row.pos_x//CHUNK_SIZE, row.pos_y//CHUNK_SIZE
    climate = _climate_of(cx, cy)

    now = _now()
    now_bucket = math.floor(now/1800.0)*1800.0
    weather = pick_weather_for_chunk(climate, infl, now_bucket, cx=cx, cy=cy, now_ts=now)

    # текущий тайл — берём из видимого окна, чтобы картинка и цифры совпадали 1-в-1
    ci, cj = pt["center"]["i"], pt["center"]["j"]
    cur = pt["tiles"][cj][ci]

    b = _building_at(row.pos_x, row.pos_y)
    uid_s = str(uid)
    if b and b.kind=="camp":
        dj = _parse_json(b.data_json)
        camp_info = {"here": True, "mine": str(b.owner_id or "")==uid_s, "temp": bool(dj.get("temp", False))}
    else:
        camp_info = {"here": False}

    # --- Доп. данные для виджета погоды/модификаторов ---
    wet, dry, cold, heat = W.env_levels(climate, weather)
    tile_base_mul = tile_fatigue_mul(cur)
    env_mul       = tile_env_fatigue_mul(cur, climate, weather)
    w_raw         = float(weather.get("fatigue_mul", 1.0))
    w_eff, _      = _weather_eff_pair(weather)

    try:
        load_totals = inventory_totals(uid)
    except Exception:
        load_totals = {"speed_mul": 1.0, "fatigue_mul": 1.0}

    load_speed_mul = float(load_totals.get("speed_mul") or 1.0)
    load_fatigue_mul = float(load_totals.get("fatigue_mul") or 1.0)

    fatigue_per_tile = _BASE_FATIGUE_PER_TILE * tile_base_mul * env_mul * w_eff * load_fatigue_mul
    rest_idle_per_sec = _BASE_REST_PER_SEC * tile_rest_mul(cur) * (1.0 / w_raw)
    rest_move_per_sec = _MOVE_REST_PER_SEC * tile_rest_mul(cur) * (1.0 / w_raw)

    base_speed = float(row.speed or 1.6)
    weather_speed_mul = float(weather.get("speed_mul") or 1.0)
    tile_speed_mul = tile_speed(cur)
    speed_effective = base_speed * tile_speed_mul * weather_speed_mul * load_speed_mul

    weather_ui = dict(weather)
    weather_ui.update({
        "env": {"wet": wet, "dry": dry, "cold": cold, "heat": heat},
        "mods": {
            "tile_base": tile_base_mul,
            "env_mul": env_mul,
            "weather_raw": w_raw,
            "weather_eff": w_eff,
            "fatigue_per_tile": fatigue_per_tile,
            "rest_idle_per_sec": rest_idle_per_sec,
            "rest_move_per_sec": rest_move_per_sec,
            "tile_speed": tile_speed_mul,
            "load_speed_mul": load_speed_mul,
            "load_fatigue_mul": load_fatigue_mul,
            "base_speed": base_speed,
            "speed_effective": speed_effective,
        }
    })

    path = json.loads(row.path_json or "[]")
    anim = None
    move_progress = None
    if path:
        nx, ny = path[0]
        step_t = _step_time(row)
        p0 = _clamp((now - float(row.last_update or now)) / max(1e-6, step_t), 0.0, 1.0)
        anim = {
            "moving": True,
            "frm": {"x": int(row.pos_x), "y": int(row.pos_y)},
            "to":  {"x": int(nx),       "y": int(ny)},
            "t": float(step_t),
            "ts": float(row.last_update),
            "p0": float(p0),
            "edge": f"{int(row.pos_x)},{int(row.pos_y)}->{int(nx)},{int(ny)}"
        }
        move_progress = p0

    return {
        "ok": True,
        "pos": {"x":row.pos_x,"y":row.pos_y},
        "screen": pt["view"],             # видимое окно 15×9
        "center_idx": pt["center"],       # где рисовать игрока в tiles
        "dest": None if row.dest_x is None else {"x":row.dest_x,"y":row.dest_y},
        "path_left": len(path),
        "speed_base": float(row.speed or 1.6),
        "tile": cur,
        "patch": pt,
        "weather": weather_ui,            # <-- отдаем обогащённый объект
        "climate": climate,
        "urbanization": infl,
        "fatigue": round(float(row.fatigue or 0.0),1),
        "resting": bool(row.resting),
        "camp": camp_info,
        "anim": anim,
        "move": {
            "moving": bool(path),
            "progress": move_progress,
            "step_t": 1.0 / max(1e-6, speed_effective),
            "speed_effective": speed_effective,
        },
        "inventory": load_totals,
        "now": now
    }

def _encode_dirs(path: List[Tuple[int,int]], sx:int, sy:int) -> str:
    dirs = []
    px, py = sx, sy
    for (x,y) in path:
        dx, dy = x - px, y - py
        if   dx == 1 and dy == 0: dirs.append('R')
        elif dx ==-1 and dy == 0: dirs.append('L')
        elif dx == 0 and dy == 1: dirs.append('D')
        elif dx == 0 and dy ==-1: dirs.append('U')
        else: pass
        px, py = x, y
    return ''.join(dirs)

def set_destination(user_or_id, tx:int, ty:int) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)

    _remove_temp_camp_here(row)

    sx,sy = int(row.pos_x), int(row.pos_y)

    # прямоугольник от старта к цели (+паддинг) для быстрого A*
    x0, x1 = sorted((sx, tx)); y0, y1 = sorted((sy, ty))
    PAD = 12
    x0 -= PAD; x1 += PAD; y0 -= PAD; y1 += PAD
    infl = _player_influence(x0,y0,x1,y1)
    now = _now()
    now_bucket = math.floor(now/1800.0)*1800.0
    bmap, omap = _rect_overlay_maps(x0,y0,x1,y1)
    ctx = _TileCtx(now_bucket=now_bucket, influence=infl, bmap=bmap, omap=omap)

    cx, cy = row.pos_x//CHUNK_SIZE, row.pos_y//CHUNK_SIZE
    climate = _climate_of(cx, cy)
    weather = pick_weather_for_chunk(climate, infl, now_bucket, cx=cx, cy=cy, now_ts=now)

    if (sx,sy)==(tx,ty):
        row.dest_x=row.dest_y=None; row.path_json="[]"; db.session.commit()
        return {"ok": True, "message":"Уже на месте"}

    path = _astar(row, tx, ty, weather, ctx=ctx)
    if not path:
        return {"ok": False, "message":"Путь не найден (вода/лава/преграды)."}

    row.dest_x, row.dest_y = int(tx), int(ty)
    row.path_json = json.dumps(path, separators=(",", ":"))
    row.last_update = _now()
    row.resting = False
    db.session.add(row); db.session.commit()

    # Вернём компактный «план» для клиента (локальная анимация без частых запросов)
    dirs = _encode_dirs(path, sx, sy)
    step_t = _step_time(row)
    return {
        "ok": True,
        "message":"Маршрут проложен",
        "steps": len(path),
        "plan": {
            "start": {"x": sx, "y": sy},
            "dirs": dirs,
            "step_t": float(step_t),
            "now": _now()
        }
    }

def stop_hero(user_or_id) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    row.dest_x=row.dest_y=None; row.path_json="[]"; row.last_update=_now()
    db.session.add(row); db.session.commit()
    return {"ok": True, "message":"Остановлен"}

def rest_here(user_or_id) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    row.resting = True
    row.dest_x=row.dest_y=None; row.path_json="[]"; row.last_update=_now()
    db.session.add(row); db.session.commit()
    return {"ok": True, "message":"Отдых начат"}

def wake_up(user_or_id) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    row.resting = False
    db.session.add(row); db.session.commit()
    return {"ok": True, "message":"Продолжаем путь"}

def set_speed(user_or_id, speed_tiles_per_sec: float) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    try:
        sp = float(speed_tiles_per_sec)
    except Exception:
        sp = 1.6
    row.speed = _clamp(sp, 0.4, 4.0)
    db.session.add(row); db.session.commit()
    return {"ok": True, "speed": row.speed}

def build_here(user_or_id, kind: str) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    x,y = int(row.pos_x), int(row.pos_y)
    base = _tile_at(x,y, for_view=False)
    if base in (T_WATER, T_LAVA):
        return {"ok": False, "message":"Нельзя строить на воде/лаве."}

    kind = (kind or "").strip().lower()
    if kind != "camp":
        return {"ok": False, "message":"Сейчас можно строить только лагерь."}

    if WorldBuilding.query.filter_by(x=x,y=y).first():
        return {"ok": False, "message":"Клетка занята постройкой."}

    b = WorldBuilding(x=x,y=y,kind="camp", owner_id=str(uid), data_json=json.dumps({"temp": False}), created_at=_now())
    db.session.add(b); db.session.commit()
    return {"ok": True, "message": "Лагерь установлен", "x":x,"y":y,"kind":kind}

def camp_start(user_or_id) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    x,y = int(row.pos_x), int(row.pos_y)
    base = _tile_at(x,y, for_view=False)
    if base in (T_WATER, T_LAVA):
        return {"ok": False, "message":"Нельзя разбить лагерь на воде/лаве."}
    b = _building_at(x,y)
    if b and b.kind!="camp":
        return {"ok": False, "message":"Клетка занята постройкой."}
    if b and b.kind=="camp":
        dj = _parse_json(b.data_json)
        if dj.get("temp") and str(b.owner_id or "")==str(uid):
            row.resting = True
            row.dest_x=row.dest_y=None; row.path_json="[]"; row.last_update=_now()
            db.session.add(row); db.session.commit()
            return {"ok": True, "message":"Вы уже в своём лагере"}
        else:
            return {"ok": False, "message":"Здесь уже стоит лагерь."}
    nb = WorldBuilding(x=x,y=y,kind="camp", owner_id=str(uid), data_json=json.dumps({"temp": True}), created_at=_now())
    db.session.add(nb)
    row.resting = True
    row.dest_x=row.dest_y=None; row.path_json="[]"; row.last_update=_now()
    db.session.add(row); db.session.commit()
    return {"ok": True, "message":"Лагерь разбит. Можно отдыхать."}

def camp_leave(user_or_id) -> Dict[str,Any]:
    ensure_world_models()
    uid = _uid(user_or_id)
    row = _get_state(uid)
    _advance(row)
    b = _temp_camp_here(row)
    if not b:
        return {"ok": False, "message":"Нет вашего временного лагеря тут."}
    db.session.delete(b)
    row.resting = False
    db.session.add(row)
    db.session.commit()
    return {"ok": True, "message":"Лагерь свёрнут. Путь свободен."}

# --- VIEW-ONLY PATCH (для подгрузки тайлов по камере) ---
def get_patch_view(cx: int, cy: int) -> Dict[str, Any]:
    ensure_world_models()
    _prefetch_ring(cx // CHUNK_SIZE, cy // CHUNK_SIZE, radius=1)
    pt = _patch(cx, cy)
    pt["view"] = {"ox": pt["ox"], "oy": pt["oy"], "w": pt["w"], "h": pt["h"]}
    return {"ok": True, "patch": pt}
