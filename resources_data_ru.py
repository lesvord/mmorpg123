# resources_data_ru.py
# Таблицы добычи по биомам + реестр предметов/весов
from dataclasses import dataclass
from typing import List, Dict, Tuple
import random

@dataclass
class Drop:
    item: str            # id ресурса
    p: float             # шанс 0..1
    qty: Tuple[int, int] # диапазон количества

# (опционально для UI) краткий справочник локальных ресурсов
ITEMS: Dict[str, Dict] = {
    "stick":      {"name": "Ветка",              "kg": 0.2, "stack": 50},
    "berries":    {"name": "Ягоды",              "kg": 0.1, "stack": 50},
    "mushroom":   {"name": "Гриб",               "kg": 0.2, "stack": 30},
    "stone":      {"name": "Камень",             "kg": 2.0, "stack": 50},
    "log":        {"name": "Бревно",             "kg": 3.0, "stack": 20},
    "reed":       {"name": "Камыш",              "kg": 0.2, "stack": 50},
    "clay":       {"name": "Глина",              "kg": 1.0, "stack": 50},
    "sand":       {"name": "Песок",              "kg": 1.0, "stack": 50},
    "cactus":     {"name": "Кактус",             "kg": 1.5, "stack": 20},
    "fish":       {"name": "Рыба",               "kg": 1.0, "stack": 20},
    "ice":        {"name": "Лёд",                "kg": 1.0, "stack": 50},
    "obsidian":   {"name": "Обсидиан",           "kg": 3.0, "stack": 20},
    "copper_ore": {"name": "Медная руда",        "kg": 3.0, "stack": 20},
    "iron_ore":   {"name": "Железная руда",      "kg": 3.2, "stack": 20},
    "gold_nug":   {"name": "Золотой самородок",  "kg": 0.5, "stack": 10},
    "gem":        {"name": "Драгоценный камень", "kg": 0.3, "stack": 10},
}

# Увеличенные таблицы дропа по биомам
BIOME_TABLE: Dict[str, List[Drop]] = {
    "grass": [
        Drop("stick",   0.90, (3, 8)),
        Drop("berries", 0.55, (2, 6)),
        Drop("stone",   0.30, (1, 3)),
        Drop("gem",     0.03, (1, 1)),
    ],
    "meadow": [
        Drop("stick",   0.70, (2, 6)),
        Drop("berries", 0.65, (2, 6)),
        Drop("stone",   0.25, (1, 3)),
    ],
    "forest": [
        Drop("log",     0.75, (1, 3)),
        Drop("stick",   0.95, (4, 10)),
        Drop("mushroom",0.55, (2, 4)),
        Drop("stone",   0.30, (1, 3)),
        Drop("gem",     0.03, (1, 1)),
    ],
    "swamp": [
        Drop("reed",    0.90, (4, 9)),
        Drop("clay",    0.70, (2, 5)),
        Drop("mushroom",0.45, (1, 3)),
    ],
    "sand": [
        Drop("sand",    0.96, (5, 12)),
        Drop("stone",   0.30, (1, 3)),
        Drop("cactus",  0.28, (1, 2)),
        Drop("gold_nug",0.05, (1, 1)),
    ],
    "desert": [
        Drop("sand",    0.97, (6, 14)),
        Drop("stone",   0.30, (1, 3)),
        Drop("cactus",  0.32, (1, 3)),
        Drop("gold_nug",0.06, (1, 1)),
    ],
    "water": [
        Drop("fish",    0.60, (1, 3)),
        Drop("stone",   0.20, (1, 2)),
    ],
    "rock": [
        Drop("stone",     0.85, (2, 5)),
        Drop("copper_ore",0.40, (1, 3)),
        Drop("iron_ore",  0.30, (1, 2)),
        Drop("gold_nug",  0.06, (1, 1)),
        Drop("gem",       0.04, (1, 1)),
    ],
    "snow": [
        Drop("ice",     0.94, (3, 8)),
        Drop("stone",   0.25, (1, 3)),
    ],
    "lava": [
        Drop("obsidian",0.40, (1, 2)),
        Drop("stone",   0.55, (1, 3)),
        Drop("gem",     0.03, (1, 1)),
    ],
    "road": [
        Drop("stone",   0.18, (1, 2)),
        Drop("stick",   0.30, (1, 3)),
    ],
    "town": [], "tavern": [], "camp": [],
}

def roll_drops(biome: str) -> List[Tuple[str, int]]:
    """Базовый бросок без погодных модификаторов (используется, если нужно)."""
    table = BIOME_TABLE.get(biome, BIOME_TABLE.get("grass", []))
    out: List[Tuple[str,int]] = []
    for d in random.sample(table, k=len(table)):
        if random.random() <= d.p:
            q = random.randint(d.qty[0], d.qty[1])
            out.append((d.item, q))
        if len(out) >= 3:
            break
    return out
