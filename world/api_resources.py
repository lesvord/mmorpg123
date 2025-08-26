from __future__ import annotations
import random
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, List

from flask import Blueprint, request, jsonify, g

# ВАЖНО: уникальное имя блюпринта, чтобы не конфликтовать с routes_world
bp = Blueprint("world_resources", __name__, url_prefix="/world")

# === Простая «память» процесса ===
INV: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))  # user_id -> item_key -> qty
FATIGUE: Dict[str, float] = defaultdict(float)                          # 0..100
CAPACITY_KG: Dict[str, float] = defaultdict(lambda: 30.0)               # дефолт 30 кг

FATIGUE_PER_TICK = 3.0             # уходит за тик добычи (5 сек)
BASE_MISS = 0.40                   # базовая вероятность «ничего не нашёл»

@dataclass
class Res:
    key: str
    name: str
    weight: float  # кг/шт
    p: float       # вес в рулетке вероятностей (больше — чаще)

# === Расширенные таблицы по биомам ===
TABLE: Dict[str, Tuple[Res, ...]] = {
    "forest": (
        Res("stick","Палки",0.10, 8),
        Res("branch","Ветви",0.18, 6),
        Res("bark","Кора",0.05, 5),
        Res("berry","Ягоды",0.05, 5),
        Res("mushroom","Грибы",0.15, 4),
        Res("resin","Смола",0.04, 3),
        Res("herb_common","Трава лечебная",0.02, 3),
        Res("rare_herb","Редкая трава",0.02, 1),
    ),
    "meadow": (
        Res("fiber","Волокно",0.05, 8),
        Res("flower","Цветы",0.02, 5),
        Res("berry","Ягоды",0.05, 4),
        Res("seed_mix","Семена",0.01, 4),
        Res("clay_lump","Ком глины",0.40, 2),
    ),
    "swamp": (
        Res("peat","Торф",0.30, 8),
        Res("reed","Камыш",0.12, 6),
        Res("mud","Ил",0.25, 4),
        Res("leech","Пиявка",0.02, 2),
        Res("frog","Лягушка",0.15, 1),
    ),
    "rock": (
        Res("stone","Камень",0.40, 9),
        Res("flint","Кремень",0.25, 6),
        Res("ore_frag","Кусок руды",0.60, 5),
        Res("coal_chunk","Уголь",0.35, 4),
        Res("crystal_shard","Осколок кристалла",0.10, 1),
    ),
    "sand": (
        Res("shell","Ракушки",0.02, 7),
        Res("salt","Соль",0.03, 5),
        Res("sea_glass","Морское стекло",0.02, 3),
        Res("amber","Янтарь",0.05, 2),
    ),
    "desert": (
        Res("salt","Соль",0.03, 7),
        Res("cactus_pulp","Мякоть кактуса",0.20, 4),
        Res("scarab","Скарабей",0.02, 2),
        Res("quartz","Кварц",0.18, 2),
    ),
    "snow": (
        Res("ice_chunk","Лёд",0.30, 7),
        Res("snow_pelt","Снежный наст",0.10, 4),
        Res("fur_scrap","Обрывок шкуры",0.08, 3),
        Res("frozen_berry","Морозная ягода",0.05, 2),
    ),
    "grass": (
        Res("fiber","Волокно",0.05, 8),
        Res("stick","Палки",0.10, 7),
        Res("small_stone","Галька",0.08, 5),
        Res("herb_common","Трава лечебная",0.02, 3),
    ),
    "water": (
        Res("fish","Рыба",0.40, 6),
        Res("algae","Водоросли",0.10, 6),
        Res("clam","Моллюск",0.15, 3),
        Res("driftwood","Коряга",0.25, 2),
    ),
    "lava": (
        Res("slag","Шлак",0.50, 7),
        Res("obsidian","Обсидиан",0.80, 3),
        Res("sulfur","Сера",0.20, 3),
    ),
    "road": (
        Res("scrap","Металлолом",0.30, 5),
        Res("nail_rusty","Ржавый гвоздь",0.02, 4),
        Res("wire_piece","Кусок проволоки",0.03, 3),
    ),
    "town": tuple(),
    "tavern": tuple(),
    "camp": tuple(),
}
FALLBACK = TABLE["grass"]

# Группы для модификаций
SET_HERBS   = {"herb_common","rare_herb","flower","seed_mix"}
SET_BERRIES = {"berry","frozen_berry"}
SET_MUSH    = {"mushroom"}
SET_WOOD    = {"stick","branch","bark","driftwood","resin"}
SET_WATER   = {"fish","algae","clam","driftwood","reed","mud","peat"}
SET_ARCTIC  = {"ice_chunk","snow_pelt","fur_scrap","frozen_berry"}
SET_DESERT  = {"salt","quartz","cactus_pulp","scarab","amber"}
SET_STONE   = {"stone","flint","ore_frag","coal_chunk","crystal_shard","small_stone"}

def _uid() -> str:
    uid = getattr(g, "user_id", None)
    if not uid:
        uid = "anon:process"
    return uid

def _resolve_biome(tile: Optional[str]) -> Tuple[Res, ...]:
    if not tile:
        return FALLBACK
    base = tile.replace("_snow", "")
    return TABLE.get(base, FALLBACK)

def _inv_weight(uid: str) -> float:
    items = INV[uid]
    total = 0.0
    for k, q in items.items():
        w = None
        for tab in TABLE.values():
            for r in tab:
                if r.key == k:
                    w = r.weight
                    break
            if w is not None:
                break
        if w is None:
            continue
        total += w * q
    return round(total, 3)

def _add_item(uid: str, r: Res, qty: int) -> bool:
    cap = CAPACITY_KG[uid]
    need = r.weight * qty
    if _inv_weight(uid) + need > cap + 1e-6:
        return False
    INV[uid][r.key] += qty
    return True

def _qty_for(r: Res) -> int:
    bulk = {"stick","branch","bark","fiber","algae","shell","salt","peat","reed",
            "mud","stone","flint","coal_chunk","small_stone","seed_mix","driftwood",
            "snow_pelt","nail_rusty","wire_piece"}
    if r.key in bulk:
        return random.randint(1, 4)
    return 1

def _miss_chance(tile: str, weather: str) -> float:
    # Базовые поправки по погоде
    w = weather.lower()
    miss = BASE_MISS
    if w == "storm":
        miss += 0.15
    elif w == "rain":
        miss += 0.05
    elif w == "snow":
        miss += 0.07
    elif w == "wind":
        miss += 0.03
    elif w == "fog":
        miss += 0.02
    elif w == "heat":
        miss += 0.04

    # Биомные льготы/штрафы
    t = tile.replace("_snow", "")
    if t in ("swamp","water") and w in ("rain","storm"):
        miss -= 0.05
    if t == "rock" and w in ("storm","rain"):
        miss += 0.04
    if t in ("desert","sand") and w == "heat":
        miss -= 0.03

    return max(0.15, min(0.70, miss))

def _apply_modifiers(tab: Tuple[Res, ...], tile: str, weather: str, climate: str) -> List[Tuple[Res, float]]:
    """
    Возвращает список (ресурс, скорректированный вес p).
    Погода и климат смещают веса, не меняя состав.
    """
    t = tile.replace("_snow", "")
    w = (weather or "").lower()
    c = (climate or "").lower()

    def mul_for(key: str) -> float:
        m = 1.0
        # Погода
        if w in ("rain","storm"):
            if key in SET_WATER:      m *= 1.35
            if key in {"branch","stick","driftwood"}: m *= 1.20
            if key in {"ore_frag","crystal_shard"}:   m *= 0.90
        if w == "snow":
            if key in SET_BERRIES:    m *= 0.50
            if key in SET_HERBS:      m *= 0.75
            if key in SET_ARCTIC:     m *= 1.30
        if w == "heat":
            if key in {"salt","quartz","cactus_pulp"}: m *= 1.25
            if key in SET_MUSH:       m *= 0.70
        if w == "fog":
            if key in SET_MUSH:       m *= 1.15
            if key in SET_HERBS:      m *= 1.10
        if w == "wind":
            if key in {"branch","stick","driftwood"}: m *= 1.20

        # Биом-специфика + погода
        if t == "swamp" and w in ("rain","storm"):
            if key in {"mud","peat","reed"}: m *= 1.25
        if t == "water" and w in ("rain","storm"):
            if key in {"fish","algae","clam","driftwood"}: m *= 1.20

        # Климат
        if c in ("arid","desert","dry","steppe"):
            if key in SET_DESERT:     m *= 1.30
            if key in SET_MUSH:       m *= 0.70
            if key in SET_WATER:      m *= 0.80
        if c in ("humid","tropical","monsoon","mediterranean","oceanic"):
            if key in (SET_HERBS | SET_BERRIES | SET_MUSH): m *= 1.20
            if key == "resin":        m *= 1.20
            if key == "salt":         m *= 0.85
        if c in ("polar","cold","alpine","tundra"):
            if key in SET_ARCTIC:     m *= 1.30
            if key in (SET_BERRIES | SET_HERBS): m *= 0.75

        return m

    out: List[Tuple[Res, float]] = []
    for r in tab:
        mult = mul_for(r.key)
        p = max(0.05, r.p * mult)  # не даём весам схлопнуться
        out.append((r, p))
    return out

def _weighted_pick_adjusted(adjusted: List[Tuple[Res, float]]) -> Optional[Res]:
    if not adjusted:
        return None
    s = sum(p for _, p in adjusted)
    if s <= 0:
        return None
    roll = random.random() * s
    acc = 0.0
    for r, p in adjusted:
        acc += p
        if roll <= acc:
            return r
    return adjusted[-1][0]

# ==== Эндпойнты ====

@bp.post("/gather/start")
def gather_start():
    _ = _uid()
    return jsonify({"ok": True})

@bp.post("/gather/stop")
def gather_stop():
    _ = _uid()
    return jsonify({"ok": True})

@bp.post("/gather/tick")
def gather_tick():
    uid = _uid()
    data = request.get_json(silent=True) or {}
    tile     = str(data.get("tile") or "")
    weather  = str((data.get("weather") or "clear")).lower()
    climate  = str((data.get("climate") or "")).lower()

    # 1) стамина
    f0 = float(FATIGUE[uid])
    if f0 >= 100.0 - 1e-6:
        return jsonify({"ok": True, "fatigue": f0, "reason": "fatigue_cap"})
    f1 = min(100.0, f0 + FATIGUE_PER_TICK)
    FATIGUE[uid] = f1

    # 2) лимит веса
    if _inv_weight(uid) >= CAPACITY_KG[uid] - 1e-6:
        return jsonify({"ok": True, "fatigue": f1, "full": True, "weight": _inv_weight(uid), "cap": CAPACITY_KG[uid]})

    # 3) промах с учётом условий
    miss = _miss_chance(tile or "grass", weather)
    tab = _resolve_biome(tile)
    if not tab or random.random() < miss:
        return jsonify({"ok": True, "fatigue": f1, "found": None, "weight": _inv_weight(uid), "cap": CAPACITY_KG[uid], "miss": round(miss,2)})

    # 4) рулетка с модификаторами погоды/климата
    adjusted = _apply_modifiers(tab, tile or "grass", weather, climate or "")
    res = _weighted_pick_adjusted(adjusted)
    if not res:
        return jsonify({"ok": True, "fatigue": f1, "found": None, "weight": _inv_weight(uid), "cap": CAPACITY_KG[uid]})

    qty = _qty_for(res)
    if not _add_item(uid, res, qty):
        return jsonify({"ok": True, "fatigue": f1, "full": True, "weight": _inv_weight(uid), "cap": CAPACITY_KG[uid]})

    return jsonify({
        "ok": True,
        "fatigue": f1,
        "found": {"key": res.key, "name": res.name, "qty": qty, "weight": res.weight},
        "weight": _inv_weight(uid),
        "cap": CAPACITY_KG[uid]
    })

@bp.get("/inventory")
def get_inventory():
    uid = _uid()
    items = []
    for k, q in INV[uid].items():
        w = 0.0; nm = k
        for tab in TABLE.values():
            for r in tab:
                if r.key == k:
                    w = r.weight; nm = r.name; break
            if w: break
        items.append({"key": k, "name": nm, "qty": q, "weight": w})
    return jsonify({"ok": True, "items": items, "weight": _inv_weight(uid), "cap": CAPACITY_KG[uid]})

@bp.post("/inventory/drop")
def drop_inventory():
    uid = _uid()
    data = request.get_json(silent=True) or {}
    key = str(data.get("key", "")).strip()
    qty = int(data.get("qty", 0) or 0)
    if not key or qty <= 0:
        return jsonify({"ok": False, "message": "bad args"}), 400
    have = INV[uid].get(key, 0)
    if have <= 0:
        return jsonify({"ok": False, "message": "no such item"}), 404
    take = min(have, qty)
    INV[uid][key] = have - take
    if INV[uid][key] <= 0:
        INV[uid].pop(key, None)
    return jsonify({"ok": True, "removed": take, "weight": _inv_weight(uid), "cap": CAPACITY_KG[uid]})
