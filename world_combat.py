from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from models import db
from accounts.models import PlayerProfile, inventory_totals
from world_models import WorldMonster, WorldCombat
from world_tiles import is_passable


@dataclass(frozen=True)
class MonsterTemplate:
    key: str
    name: str
    role: str
    attack: float
    defense: float
    hp: float
    agility: float


# Подборки монстров по биомам
_MONSTER_TEMPLATES: Dict[str, Sequence[MonsterTemplate]] = {
    "forest": (
        MonsterTemplate("wolf", "Лесной волк", "скрыватель", 1.05, 0.8, 0.85, 1.25),
        MonsterTemplate("boar", "Дикий кабан", "танк", 0.95, 1.25, 1.35, 0.7),
        MonsterTemplate("entling", "Древесный энт", "контролёр", 1.15, 1.1, 1.45, 0.6),
    ),
    "meadow": (
        MonsterTemplate("fox", "Полевая лисица", "разведчик", 0.9, 0.7, 0.75, 1.4),
        MonsterTemplate("stag", "Разъярённый олень", "рывок", 1.0, 0.95, 1.05, 1.1),
    ),
    "grass": (
        MonsterTemplate("kobold", "Кобольд-разбойник", "пехотинец", 1.0, 0.9, 0.9, 1.15),
        MonsterTemplate("wasp", "Оса-матка", "дебаффер", 0.85, 0.75, 0.8, 1.35),
    ),
    "swamp": (
        MonsterTemplate("lizard", "Болотная ящерица", "удар", 1.15, 1.1, 1.2, 0.8),
        MonsterTemplate("mireling", "Грязевой элементаль", "контролёр", 0.95, 1.2, 1.4, 0.6),
    ),
    "desert": (
        MonsterTemplate("scarab", "Песчаный скарабей", "броня", 0.9, 1.3, 1.25, 0.75),
        MonsterTemplate("viper", "Пустынная гадюка", "яд", 1.25, 0.85, 0.9, 1.2),
    ),
    "sand": (
        MonsterTemplate("scout", "Кочевник-разведчик", "пехотинец", 1.05, 0.95, 0.95, 1.05),
        MonsterTemplate("hyena", "Гиена", "стая", 1.1, 0.8, 0.85, 1.3),
    ),
    "rock": (
        MonsterTemplate("golem", "Каменный голем", "щит", 1.05, 1.45, 1.6, 0.55),
        MonsterTemplate("troll", "Скалистый тролль", "берсерк", 1.35, 1.15, 1.5, 0.65),
    ),
    "snow": (
        MonsterTemplate("yeti", "Йети", "давление", 1.25, 1.25, 1.55, 0.7),
        MonsterTemplate("frost_wolf", "Морозный волк", "налёт", 1.15, 0.9, 0.95, 1.25),
    ),
    "water": (
        MonsterTemplate("pike", "Озерная щука", "рывок", 1.15, 0.85, 0.95, 1.3),
        MonsterTemplate("slime", "Грязевой слизень", "замедление", 0.9, 0.8, 1.2, 0.6),
    ),
}

_DEFAULT_TEMPLATES: Sequence[MonsterTemplate] = (
    MonsterTemplate("rogue", "Странник", "универсал", 1.0, 1.0, 1.0, 1.0),
    MonsterTemplate("bandit", "Разбойник", "налётчик", 1.15, 0.95, 0.95, 1.05),
)

_BOSS_TEMPLATES: Sequence[MonsterTemplate] = (
    MonsterTemplate("ancient_wyrm", "Древний виверн", "босс", 1.6, 1.35, 1.9, 1.1),
    MonsterTemplate("spirit_guard", "Страж духа", "босс", 1.4, 1.6, 1.75, 0.9),
    MonsterTemplate("lich", "Полузабытый лич", "босс", 1.5, 1.3, 1.5, 1.0),
)

# Вспомогательные коэффициенты
_MAX_NEAR_MONSTERS = 5
_MONSTER_RADIUS = 3
_FAR_DESPAWN_RADIUS = 8
_DEFEATED_TTL = 60.0
_IDLE_TTL = 240.0


def _now() -> float:
    return time.time()


def _uid_str(user_id: int) -> str:
    return str(int(user_id))


def _tile_passable(tile_id: str) -> bool:
    base = (tile_id or "").split("_", 1)[0]
    if base in {"water", "lava"}:
        return False
    try:
        return bool(is_passable(base))
    except Exception:
        return True


def _biome_from_tile(tile_id: str) -> str:
    return (tile_id or "").split("_", 1)[0] or "grass"


def _templates_for_biome(biome: str, boss: bool = False) -> Sequence[MonsterTemplate]:
    if boss:
        return _BOSS_TEMPLATES
    return _MONSTER_TEMPLATES.get(biome, _DEFAULT_TEMPLATES)


def _template_by_key(key: str) -> MonsterTemplate:
    for seq in list(_MONSTER_TEMPLATES.values()) + [ _DEFAULT_TEMPLATES, _BOSS_TEMPLATES ]:
        for tpl in seq:
            if tpl.key == key:
                return tpl
    return _DEFAULT_TEMPLATES[0]


def _candidate_tiles(patch: Dict[str, Any], hero_x: int, hero_y: int, radius: int) -> List[Tuple[int, int, str, str]]:
    tiles = patch.get("tiles") or []
    width = int(patch.get("w") or (len(tiles[0]) if tiles else 0))
    height = int(patch.get("h") or len(tiles))
    ox = int(patch.get("ox") or (hero_x - width // 2))
    oy = int(patch.get("oy") or (hero_y - height // 2))
    occupied = {(int(b.get("x")), int(b.get("y"))) for b in (patch.get("buildings") or []) if b}

    result: List[Tuple[int, int, str, str]] = []
    for j, row in enumerate(tiles):
        for i, tile in enumerate(row):
            x = ox + i
            y = oy + j
            dist = max(abs(x - hero_x), abs(y - hero_y))
            if dist == 0 or dist > radius:
                continue
            if (x, y) in occupied:
                continue
            if not _tile_passable(tile):
                continue
            biome = _biome_from_tile(tile)
            result.append((x, y, biome, tile))
    return result


def _ensure_profile(user_id: int) -> PlayerProfile:
    profile = PlayerProfile.query.get(user_id)
    if profile:
        return profile
    profile = PlayerProfile(user_id=user_id)
    db.session.add(profile)
    db.session.commit()
    return profile


def _load_totals(user_id: int) -> Dict[str, float]:
    try:
        return inventory_totals(user_id)
    except Exception:
        return {}


def _apply_stats(monster: WorldMonster, template: MonsterTemplate, sheet: Dict[str, float]):
    level_ratio = max(0.6, monster.level / max(1.0, float(sheet.get("level", 1))))
    boss_mul = 1.55 if monster.is_boss else 1.0

    hp_max = sheet.get("hp_max", 80)
    attack = sheet.get("attack", 12)
    defense = sheet.get("defense", 8)
    agility = sheet.get("agility", 6)

    hp_scale = (0.55 + 0.28 * level_ratio) * template.hp * boss_mul
    atk_scale = (0.6 + 0.30 * level_ratio) * template.attack * (1.25 if monster.is_boss else 1.0)
    def_scale = (0.6 + 0.26 * level_ratio) * template.defense * (1.2 if monster.is_boss else 1.0)
    agi_scale = (0.65 + 0.22 * level_ratio) * template.agility

    monster.hp_max = max(30, int(round(hp_max * hp_scale)))
    monster.hp = max(1, min(monster.hp_max, int(round(monster.hp if monster.hp else monster.hp_max))))
    monster.attack = max(3, int(round(attack * atk_scale)))
    monster.defense = max(2, int(round(defense * def_scale)))
    monster.agility = max(2, int(round(agility * agi_scale)))

    power_score = monster.attack * 1.2 + monster.defense + monster.hp_max / 8.0
    payload = {
        "role": template.role,
        "power": round(power_score, 1),
        "biome": monster.biome,
    }
    monster.data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _spawn_monster(user_id: int, x: int, y: int, biome: str, profile: PlayerProfile, sheet: Dict[str, float]) -> WorldMonster:
    uid_s = _uid_str(user_id)
    is_boss = random.random() < 0.08
    templates = _templates_for_biome(biome, boss=is_boss)
    template = random.choice(tuple(templates))
    level_base = max(1, int(sheet.get("level", profile.level)))
    if is_boss:
        diff = random.randint(5, 10)
        if random.random() < 0.4:
            diff = -diff
    else:
        diff = random.randint(-2, 2)
    level = max(1, level_base + diff)

    now = _now()
    monster = WorldMonster(
        user_id=uid_s,
        x=int(x),
        y=int(y),
        biome=biome,
        kind=template.role,
        name=template.name,
        template_key=template.key,
        level=level,
        is_boss=is_boss,
        hp=1,
        hp_max=1,
        attack=1,
        defense=1,
        agility=1,
        xp_reward=int(40 + level * 12 * (1.6 if is_boss else 1.0)),
        gold_reward=int(6 + level * (3 if is_boss else 2)),
        state="idle",
        spawned_at=now,
        updated_at=now,
    )
    _apply_stats(monster, template, sheet)
    monster.hp = monster.hp_max
    db.session.add(monster)
    return monster


def _cleanup_monsters(user_id: int, hero_x: int, hero_y: int):
    uid_s = _uid_str(user_id)
    rows: List[WorldMonster] = WorldMonster.query.filter_by(user_id=uid_s).all()
    if not rows:
        return
    now = _now()
    removed = False
    for row in rows:
        dist = max(abs(int(row.x) - hero_x), abs(int(row.y) - hero_y))
        if row.state == "defeated" and now - float(row.updated_at or 0.0) > _DEFEATED_TTL:
            db.session.delete(row)
            removed = True
            continue
        if dist > _FAR_DESPAWN_RADIUS and now - float(row.updated_at or 0.0) > _IDLE_TTL:
            db.session.delete(row)
            removed = True
    if removed:
        db.session.commit()


def _retune_monster(monster: WorldMonster, sheet: Dict[str, float]):
    template = _template_by_key(monster.template_key)
    prev_state = monster.state
    prev_hp_frac = 1.0
    if monster.hp_max:
        prev_hp_frac = max(0.0, min(1.0, monster.hp / float(monster.hp_max)))
    _apply_stats(monster, template, sheet)
    if prev_state != "engaged":
        monster.hp = int(max(1, monster.hp_max * prev_hp_frac))
    monster.updated_at = _now()
    db.session.add(monster)


def ensure_monsters_for_view(user_id: int, hero_x: int, hero_y: int, patch: Dict[str, Any],
                              profile: PlayerProfile, sheet: Dict[str, float]) -> List[Dict[str, Any]]:
    _cleanup_monsters(user_id, hero_x, hero_y)

    uid_s = _uid_str(user_id)
    candidates = _candidate_tiles(patch, hero_x, hero_y, _MONSTER_RADIUS)
    random.shuffle(candidates)

    existing: List[WorldMonster] = (
        WorldMonster.query
        .filter_by(user_id=uid_s)
        .filter(WorldMonster.x >= hero_x - _MONSTER_RADIUS, WorldMonster.x <= hero_x + _MONSTER_RADIUS,
                WorldMonster.y >= hero_y - _MONSTER_RADIUS, WorldMonster.y <= hero_y + _MONSTER_RADIUS)
        .all()
    )

    # Подтягиваем статы под игрока
    retuned = False
    for row in existing:
        if row.state != "engaged":
            _retune_monster(row, sheet)
            retuned = True

    active = [row for row in existing if row.state != "defeated"]

    spawned = False
    if len(active) < min(len(candidates), _MAX_NEAR_MONSTERS):
        needed = min(_MAX_NEAR_MONSTERS, len(candidates)) - len(active)
        taken_coords = {(m.x, m.y) for m in active}
        for x, y, biome, _tile in candidates:
            if needed <= 0:
                break
            if (x, y) in taken_coords:
                continue
            monster = _spawn_monster(user_id, x, y, biome, profile, sheet)
            taken_coords.add((x, y))
            active.append(monster)
            needed -= 1
            spawned = True

    if retuned or spawned:
        db.session.commit()

    active.sort(key=lambda m: max(abs(int(m.x) - hero_x), abs(int(m.y) - hero_y)))
    return [_serialize_monster(m, hero_x, hero_y) for m in active if m.state != "defeated"]


def _read_log(combat: WorldCombat) -> List[Dict[str, Any]]:
    try:
        log = json.loads(combat.log_json or "[]")
        if isinstance(log, list):
            return log
    except Exception:
        pass
    return []


def _write_log(combat: WorldCombat, entries: Iterable[Dict[str, Any]]):
    data = list(entries)[-24:]
    combat.log_json = json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _serialize_monster(monster: WorldMonster, hero_x: Optional[int] = None, hero_y: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "id": monster.id,
        "name": monster.name,
        "kind": monster.kind,
        "level": monster.level,
        "is_boss": bool(monster.is_boss),
        "hp": int(monster.hp),
        "hp_max": int(monster.hp_max),
        "attack": int(monster.attack),
        "defense": int(monster.defense),
        "agility": int(monster.agility),
        "xp_reward": int(monster.xp_reward),
        "gold_reward": int(monster.gold_reward),
        "coords": {"x": int(monster.x), "y": int(monster.y)},
        "state": monster.state,
    }
    try:
        extra = json.loads(monster.data_json or "{}")
        if isinstance(extra, dict):
            payload.update(extra)
    except Exception:
        pass
    if hero_x is not None and hero_y is not None:
        payload["distance"] = max(abs(int(monster.x) - hero_x), abs(int(monster.y) - hero_y))
    payload["hp_frac"] = 0.0 if monster.hp_max <= 0 else round(monster.hp / float(monster.hp_max), 3)
    return payload


def combat_snapshot(user_id: int, sheet: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    combat = WorldCombat.query.filter_by(user_id=_uid_str(user_id)).first()
    if not combat or not combat.monster:
        return {"active": False, "state": "idle", "log": []}
    monster = combat.monster
    if monster.state == "defeated" and combat.state == "active":
        combat.state = "won"
        db.session.add(combat)
        db.session.commit()
    log = _read_log(combat)
    profile = PlayerProfile.query.get(user_id)
    if sheet is None and profile:
        sheet = profile.combat_snapshot()
    if sheet is None:
        sheet = {"hp_max": combat.player_hp_max, "attack": 10, "defense": 8, "agility": 6}
    player_hp = max(0, min(int(combat.player_hp), int(sheet.get("hp_max", combat.player_hp_max))))
    player_payload = {
        "hp": player_hp,
        "hp_max": int(combat.player_hp_max),
        "stats": sheet,
    }
    return {
        "active": combat.state == "active",
        "state": combat.state,
        "turn": combat.turn,
        "player": player_payload,
        "monster": _serialize_monster(monster),
        "log": log,
        "updated_at": combat.updated_at,
    }


def engage_monster(user_id: int, monster_id: int) -> Dict[str, Any]:
    uid_s = _uid_str(user_id)
    monster = WorldMonster.query.filter_by(id=monster_id, user_id=uid_s).first()
    if not monster:
        return {"ok": False, "message": "monster_not_found"}
    if monster.state == "defeated":
        return {"ok": False, "message": "monster_defeated"}

    profile = _ensure_profile(user_id)
    load = _load_totals(user_id)
    sheet = profile.combat_snapshot(load)

    combat = WorldCombat.query.filter_by(user_id=uid_s).first()
    now = _now()
    if combat and combat.state == "active" and combat.monster_id != monster.id:
        return {
            "ok": False,
            "message": "already_in_combat",
            "combat": combat_snapshot(user_id, sheet),
        }

    opening_log = [{"type": "start", "text": f"{monster.name} готовится к бою."}]

    if combat is None:
        combat = WorldCombat(
            user_id=uid_s,
            monster_id=monster.id,
            player_hp=sheet.get("hp_max", 80),
            player_hp_max=sheet.get("hp_max", 80),
            turn=1,
            log_json=json.dumps(opening_log, ensure_ascii=False, separators=(",", ":")),
            state="active",
            started_at=now,
            updated_at=now,
        )
    else:
        combat.monster_id = monster.id
        combat.player_hp_max = sheet.get("hp_max", 80)
        combat.player_hp = combat.player_hp_max
        combat.turn = 1
        combat.state = "active"
        combat.started_at = now
        combat.updated_at = now
        _write_log(combat, opening_log)

    monster.state = "engaged"
    if monster.hp <= 0:
        monster.hp = monster.hp_max
    monster.updated_at = now

    db.session.add(monster)
    db.session.add(combat)
    db.session.commit()

    return {
        "ok": True,
        "message": "combat_started",
        "combat": combat_snapshot(user_id, sheet),
        "player": profile.as_dict(),
    }


def _hit_chance(attacker_agility: float, defender_agility: float, base: float) -> float:
    diff = max(-60.0, min(60.0, attacker_agility - defender_agility))
    chance = base + diff * 0.0045
    return max(0.18, min(0.95, chance))


def _damage(attack: float, defense: float, crit: bool) -> int:
    base = max(2.0, attack - defense * 0.52)
    roll = random.uniform(0.9, 1.12)
    dmg = base * roll
    if crit:
        dmg *= 1.55
    return max(1, int(round(dmg)))


def _append_log(combat: WorldCombat, *entries: Dict[str, Any]):
    log = _read_log(combat)
    log.extend(entries)
    _write_log(combat, log)


def _victory_rewards(profile: PlayerProfile, monster: WorldMonster) -> Dict[str, Any]:
    xp_gain = int(monster.xp_reward)
    gold_gain = int(monster.gold_reward)
    before, after = profile.add_xp(xp_gain)
    profile.add_gold(gold_gain)
    db.session.add(profile)
    return {
        "xp": xp_gain,
        "gold": gold_gain,
        "level_before": before,
        "level_after": after,
        "leveled": after > before,
    }


def attack_monster(user_id: int) -> Dict[str, Any]:
    uid_s = _uid_str(user_id)
    combat = WorldCombat.query.filter_by(user_id=uid_s).first()
    if not combat or combat.state != "active":
        return {"ok": False, "message": "no_active_combat"}

    monster = combat.monster
    if monster is None:
        combat.state = "won"
        db.session.add(combat)
        db.session.commit()
        return {"ok": False, "message": "monster_missing"}

    profile = _ensure_profile(user_id)
    load = _load_totals(user_id)
    sheet = profile.combat_snapshot(load)

    player_hp = int(combat.player_hp)
    monster_hp = int(monster.hp)

    now = _now()
    events: List[Dict[str, Any]] = []

    player_hits_first = sheet.get("agility", 0) >= monster.agility or random.random() < 0.5

    # Ход игрока
    if player_hits_first:
        hit = random.random() <= _hit_chance(sheet.get("agility", 0), monster.agility, 0.74)
        if hit:
            crit = random.random() <= sheet.get("crit", 0.05)
            dmg = _damage(sheet.get("attack", 10), monster.defense, crit)
            monster_hp = max(0, monster_hp - dmg)
            events.append({"type": "hit", "who": "player", "value": dmg, "crit": crit})
        else:
            events.append({"type": "miss", "who": "player"})

    # Ответ монстра, если он жив
    if monster_hp > 0:
        dodge_factor = max(0.0, min(0.6, sheet.get("dodge", 0.03)))
        hit_chance = _hit_chance(monster.agility, sheet.get("agility", 0), 0.7) * (1.0 - dodge_factor)
        hit = random.random() <= hit_chance
        if hit:
            crit_ch = 0.08 + monster.agility * 0.0025 + (0.05 if monster.is_boss else 0.0)
            crit = random.random() <= min(0.45, crit_ch)
            dmg = _damage(monster.attack, sheet.get("defense", 8), crit)
            player_hp = max(0, player_hp - dmg)
            events.append({"type": "hit", "who": "monster", "value": dmg, "crit": crit})
        else:
            events.append({"type": "miss", "who": "monster"})

    # Если игрок бил вторым — проведём его атаку после ответа монстра
    if not player_hits_first and player_hp > 0 and monster_hp > 0:
        hit = random.random() <= _hit_chance(sheet.get("agility", 0), monster.agility, 0.74)
        if hit:
            crit = random.random() <= sheet.get("crit", 0.05)
            dmg = _damage(sheet.get("attack", 10), monster.defense, crit)
            monster_hp = max(0, monster_hp - dmg)
            events.append({"type": "hit", "who": "player", "value": dmg, "crit": crit})
        else:
            events.append({"type": "miss", "who": "player"})

    rewards: Optional[Dict[str, Any]] = None
    if monster_hp <= 0:
        monster.state = "defeated"
        monster.hp = 0
        monster.updated_at = now
        combat.state = "won"
        rewards = _victory_rewards(profile, monster)
        events.append({"type": "end", "result": "victory", "rewards": rewards})
    elif player_hp <= 0:
        combat.state = "lost"
        player_hp = 0
        monster.state = "idle"
        monster.hp = monster.hp_max
        monster.updated_at = now
        events.append({"type": "end", "result": "defeat"})

    combat.player_hp = player_hp
    combat.player_hp_max = sheet.get("hp_max", combat.player_hp_max)
    combat.turn += 1
    combat.updated_at = now

    _append_log(combat, *events)

    db.session.add(monster)
    db.session.add(combat)
    db.session.commit()

    payload = {"ok": True, "combat": combat_snapshot(user_id, sheet)}
    if rewards:
        payload["rewards"] = rewards
    return payload


def flee_combat(user_id: int) -> Dict[str, Any]:
    uid_s = _uid_str(user_id)
    combat = WorldCombat.query.filter_by(user_id=uid_s).first()
    if not combat or combat.state != "active":
        return {"ok": False, "message": "no_active_combat"}

    monster = combat.monster
    if monster is None:
        combat.state = "won"
        db.session.add(combat)
        db.session.commit()
        return {"ok": True, "combat": combat_snapshot(user_id)}

    profile = _ensure_profile(user_id)
    load = _load_totals(user_id)
    sheet = profile.combat_snapshot(load)

    dodge_factor = sheet.get("dodge", 0.05)
    base = 0.35 + (sheet.get("agility", 0) - monster.agility) * 0.012
    if monster.is_boss:
        base -= 0.18
    chance = max(0.12, min(0.9, base + dodge_factor * 0.35))

    success = random.random() <= chance
    now = _now()

    if success:
        combat.state = "fled"
        combat.updated_at = now
        monster.state = "idle"
        monster.hp = monster.hp_max
        monster.updated_at = now
        _append_log(combat, {"type": "flee", "success": True})
    else:
        # наказание за неудачный побег — удар монстра
        hit = random.random() <= _hit_chance(monster.agility, sheet.get("agility", 0), 0.68)
        if hit:
            dmg = _damage(monster.attack, sheet.get("defense", 8), False)
            combat.player_hp = max(0, combat.player_hp - dmg)
            _append_log(combat, {"type": "flee", "success": False, "counter": dmg})
            if combat.player_hp <= 0:
                combat.state = "lost"
                monster.state = "idle"
                monster.hp = monster.hp_max
                monster.updated_at = now
                _append_log(combat, {"type": "end", "result": "defeat"})
        else:
            _append_log(combat, {"type": "flee", "success": False, "counter": 0})
        combat.updated_at = now

    db.session.add(combat)
    db.session.add(monster)
    db.session.commit()

    return {"ok": True, "combat": combat_snapshot(user_id, sheet), "escaped": success}


def sync_combat_and_monsters(user_id: int, hero_x: int, hero_y: int, patch: Dict[str, Any],
                             load_totals: Optional[Dict[str, float]] = None) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    profile = _ensure_profile(user_id)
    sheet = profile.combat_snapshot(load_totals)
    monsters = ensure_monsters_for_view(user_id, hero_x, hero_y, patch, profile, sheet)
    combat = combat_snapshot(user_id, sheet)

    player_info = profile.as_dict()
    player_info.update({
        "combat": sheet,
        "hp_max": sheet.get("hp_max", combat.get("player", {}).get("hp_max", 0)),
        "hp": combat.get("player", {}).get("hp", sheet.get("hp_max", 0)) if combat.get("active") or combat.get("state") in {"won", "lost", "fled"} else sheet.get("hp_max", 0),
    })

    return player_info, monsters, combat
