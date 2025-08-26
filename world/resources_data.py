# Таблицы добычи по биомам + реестр предметов

from dataclasses import dataclass
from typing import List, Dict, Tuple
import random

@dataclass
class Drop:
    item: str            # id предмета
    p: float             # шанс 0..1
    qty: Tuple[int,int]  # диапазон количества (в штуках)

# Справочник предметов: вес (кг) за 1 шт и макс. размер стака
ITEMS: Dict[str, Dict] = {
    "stick":      {"name": "Ветка",         "kg": 0.2, "stack": 50},
    "berries":    {"name": "Ягоды",         "kg": 0.1, "stack": 50},
    "mushroom":   {"name": "Гриб",          "kg": 0.2, "stack": 30},
    "stone":      {"name": "Камень",        "kg": 2.0, "stack": 20},
    "log":        {"name": "Бревно",        "kg": 3.0, "stack": 10},
    "reed":       {"name": "Камыш",         "kg": 0.2, "stack": 50},
    "clay":       {"name": "Глина",         "kg": 1.0, "stack": 30},
    "sand":       {"name": "Песок",         "kg": 1.0, "stack": 50},
    "cactus":     {"name": "Кактус",        "kg": 1.5, "stack": 10},
    "fish":       {"name": "Рыба",          "kg": 1.0, "stack": 20},
    "ice":        {"name": "Лёд",           "kg": 1.0, "stack": 30},
    "obsidian":   {"name": "Обсидиан",      "kg": 3.0, "stack": 10},
    "copper_ore": {"name": "Медная руда",   "kg": 3.0, "stack": 10},
    "iron_ore":   {"name": "Железная руда", "kg": 3.2, "stack": 10},
    "gold_nug":   {"name": "Золотой самородок","kg":0.5,"stack":10},
    "gem":        {"name": "Драгоценный камень","kg":0.3,"stack":10},
}

# Дроп-таблицы для биомов (id тайла -> список Drop)
BIOME_TABLE: Dict[str, List[Drop]] = {
    "grass": [
        Drop("stick", 0.85, (2,6)),
        Drop("berries", 0.45, (1,4)),
        Drop("stone", 0.25, (1,2)),
        Drop("gem", 0.02, (1,1)),
    ],
    "meadow": [
        Drop("stick", 0.6, (1,3)),
        Drop("berries", 0.55, (1,4)),
        Drop("stone", 0.2, (1,2)),
    ],
    "forest": [
        Drop("log", 0.7, (1,2)),
        Drop("stick", 0.9, (3,8)),
        Drop("mushroom", 0.5, (1,3)),
        Drop("stone", 0.25, (1,2)),
        Drop("gem", 0.02, (1,1)),
    ],
    "swamp": [
        Drop("reed", 0.8, (3,7)),
        Drop("clay", 0.6, (1,3)),
        Drop("mushroom", 0.35, (1,2)),
    ],
    "sand": [
        Drop("sand", 0.9, (3,8)),
        Drop("stone", 0.25, (1,2)),
        Drop("cactus", 0.2, (1,1)),
        Drop("gold_nug", 0.03, (1,1)),
    ],
    "desert": [
        Drop("sand", 0.95, (4,10)),
        Drop("stone", 0.25, (1,2)),
        Drop("cactus", 0.25, (1,2)),
        Drop("gold_nug", 0.04, (1,1)),
    ],
    "water": [
        Drop("fish", 0.55, (1,2)),
        Drop("stone", 0.15, (1,1)),
    ],
    "rock": [
        Drop("stone", 0.8, (1,3)),
        Drop("copper_ore", 0.35, (1,2)),
        Drop("iron_ore", 0.25, (1,2)),
        Drop("gold_nug", 0.05, (1,1)),
        Drop("gem", 0.03, (1,1)),
    ],
    "snow": [
        Drop("ice", 0.9, (2,6)),
        Drop("stone", 0.2, (1,2)),
    ],
    "lava": [
        Drop("obsidian", 0.35, (1,1)),
        Drop("stone", 0.5, (1,2)),
        Drop("gem", 0.02, (1,1)),
    ],
    "road": [  # скудно
        Drop("stone", 0.15, (1,1)),
        Drop("stick", 0.25, (1,2)),
    ],
    "town": [], "tavern": [], "camp": [],
}

def roll_drops(biome: str) -> List[Tuple[str, int]]:
    """Вернёт список (item_id, qty). До 2-3 предметов за одно действие, но не более сработавших бросков."""
    table = BIOME_TABLE.get(biome, BIOME_TABLE.get("grass", []))
    out: List[Tuple[str,int]] = []
    # случайно перемешаем, чтобы не всегда в одном порядке
    for d in random.sample(table, k=len(table)):
        if random.random() <= d.p:
            q = random.randint(d.qty[0], d.qty[1])
            out.append((d.item, q))
        if len(out) >= 3:
            break
    return out
