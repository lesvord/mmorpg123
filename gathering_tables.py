"""Shared gather mode definitions and drop tables for resource collection."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Optional, List


@dataclass(frozen=True)
class DropK:
    key: str
    w: int


@dataclass(frozen=True)
class GatherMode:
    key: str
    title: str
    icon: str
    description: str
    tables: Dict[str, Tuple[DropK, ...]]
    fallback: str = "grass"

    def table_for(self, biome: str) -> Tuple[DropK, ...]:
        if not biome:
            return self.tables.get(self.fallback, tuple())
        base = biome.split("_", 1)[0].lower()
        return self.tables.get(base, self.tables.get(self.fallback, tuple()))


# --- Base drop tables kept close to their previous values ---
_default_tables: Dict[str, Tuple[DropK, ...]] = {
    "grass": (
        DropK("res_stick", 9),
        DropK("res_fiber", 7),
        DropK("res_berries", 5),
        DropK("res_herb", 3),
        DropK("res_stone", 3),
    ),
    "forest": (
        DropK("res_stick", 10),
        DropK("res_wood_log", 6),
        DropK("res_mushroom", 5),
        DropK("res_berries", 4),
        DropK("res_stone", 2),
    ),
    "swamp": (
        DropK("res_reed", 8),
        DropK("res_clay", 6),
        DropK("res_peat", 5),
        DropK("res_mushroom", 3),
        DropK("res_fish", 2),
    ),
    "rock": (
        DropK("res_stone", 9),
        DropK("res_copper_ore", 5),
        DropK("res_iron_ore", 4),
        DropK("res_gold_nug", 1),
        DropK("res_gem", 1),
    ),
    "sand": (
        DropK("res_sand", 10),
        DropK("res_stone", 3),
        DropK("res_cactus", 3),
        DropK("res_gold_nug", 1),
    ),
    "desert": (
        DropK("res_sand", 10),
        DropK("res_cactus", 4),
        DropK("res_stone", 3),
        DropK("res_gold_nug", 1),
    ),
    "water": (
        DropK("res_fish", 6),
        DropK("res_reed", 6),
        DropK("res_sand", 2),
    ),
    "snow": (
        DropK("res_ice", 8),
        DropK("res_stone", 3),
        DropK("res_berries", 1),
    ),
    "lava": (
        DropK("res_obsidian", 2),
        DropK("res_stone", 4),
        DropK("res_gem", 1),
    ),
    "road": (
        DropK("res_stick", 3),
        DropK("res_stone", 3),
    ),
    "town": tuple(),
    "tavern": tuple(),
    "camp": tuple(),
}


# Focused tables for chopping trees / harvesting wood depending on biome.
_tree_tables: Dict[str, Tuple[DropK, ...]] = {
    "forest": (
        DropK("res_wood_log", 12),
        DropK("res_stick", 10),
        DropK("res_mushroom", 4),
        DropK("res_herb", 3),
    ),
    "swamp": (
        DropK("res_wood_log", 6),
        DropK("res_reed", 7),
        DropK("res_peat", 5),
        DropK("res_stick", 5),
    ),
    "grass": (
        DropK("res_stick", 9),
        DropK("res_wood_log", 5),
        DropK("res_fiber", 5),
    ),
    "meadow": (
        DropK("res_stick", 9),
        DropK("res_fiber", 7),
        DropK("res_wood_log", 4),
    ),
    "sand": (
        DropK("res_cactus", 8),
        DropK("res_wood_log", 3),
        DropK("res_stick", 4),
    ),
    "desert": (
        DropK("res_cactus", 10),
        DropK("res_stick", 4),
    ),
    "snow": (
        DropK("res_wood_log", 7),
        DropK("res_stick", 8),
        DropK("res_ice", 4),
    ),
    "rock": (
        DropK("res_stick", 6),
        DropK("res_wood_log", 3),
    ),
}


# Focused tables for mining stone/ore in different terrains.
_ore_tables: Dict[str, Tuple[DropK, ...]] = {
    "rock": (
        DropK("res_stone", 12),
        DropK("res_iron_ore", 6),
        DropK("res_copper_ore", 6),
        DropK("res_gold_nug", 2),
        DropK("res_gem", 2),
    ),
    "snow": (
        DropK("res_stone", 10),
        DropK("res_iron_ore", 5),
        DropK("res_ice", 4),
    ),
    "desert": (
        DropK("res_stone", 9),
        DropK("res_copper_ore", 4),
        DropK("res_gold_nug", 3),
    ),
    "sand": (
        DropK("res_stone", 8),
        DropK("res_copper_ore", 4),
        DropK("res_gold_nug", 2),
    ),
    "forest": (
        DropK("res_stone", 9),
        DropK("res_copper_ore", 3),
        DropK("res_iron_ore", 3),
    ),
    "grass": (
        DropK("res_stone", 8),
        DropK("res_copper_ore", 3),
    ),
    "lava": (
        DropK("res_obsidian", 6),
        DropK("res_stone", 5),
        DropK("res_gem", 3),
    ),
}


DEFAULT_MODE_KEY = "forage"

GATHER_MODES: Dict[str, GatherMode] = {
    "forage": GatherMode(
        key="forage",
        title="Сбор",
        icon="🌿",
        description="Сбор трав, ягод и общих ресурсов в округе.",
        tables=_default_tables,
        fallback="grass",
    ),
    "wood": GatherMode(
        key="wood",
        title="Деревья",
        icon="🌲",
        description="Рубка деревьев и сбор древесины.",
        tables=_tree_tables,
        fallback="forest",
    ),
    "ore": GatherMode(
        key="ore",
        title="Камни",
        icon="🪨",
        description="Добыча камня и руды.",
        tables=_ore_tables,
        fallback="rock",
    ),
}


def normalize_mode(key: Optional[str]) -> GatherMode:
    if not key:
        return GATHER_MODES[DEFAULT_MODE_KEY]
    norm = str(key).strip().lower()
    return GATHER_MODES.get(norm, GATHER_MODES[DEFAULT_MODE_KEY])


def serialize_modes() -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for mode in GATHER_MODES.values():
        out.append(
            {
                "key": mode.key,
                "title": mode.title,
                "icon": mode.icon,
                "description": mode.description,
            }
        )
    return out

