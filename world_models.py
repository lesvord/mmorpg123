# world_models.py
import json
from models import db
from sqlalchemy import UniqueConstraint

class WorldState(db.Model):
    __tablename__ = "world_state"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), unique=True, nullable=False, index=True)

    pos_x = db.Column(db.Integer, nullable=False, default=0)
    pos_y = db.Column(db.Integer, nullable=False, default=0)

    dest_x = db.Column(db.Integer)
    dest_y = db.Column(db.Integer)
    path_json = db.Column(db.Text, nullable=False, default="[]")

    last_update = db.Column(db.Float, nullable=False)

    # базовая скорость (клеток/сек) — дополнительно умножается на модификаторы тайла и погоды
    speed = db.Column(db.Float, nullable=False, default=1.6)

    # Новые системы
    fatigue = db.Column(db.Float, nullable=False, default=15.0)  # 0..100 (чем выше — тем сильнее усталость)
    resting = db.Column(db.Boolean, nullable=False, default=False)  # герой отдыхает/спит на месте


class WorldChunk(db.Model):
    __tablename__ = "world_chunks"
    id = db.Column(db.Integer, primary_key=True)
    cx = db.Column(db.Integer, nullable=False)
    cy = db.Column(db.Integer, nullable=False)
    size = db.Column(db.Integer, nullable=False, default=32)

    # Основные данные
    tiles_json   = db.Column(db.Text, nullable=False)   # [["grass",...], ...]
    climate_json = db.Column(db.Text, nullable=False)   # {"height_mean":..,"moist":..,"temp":..,"forest_density":..}
    created_at   = db.Column(db.Float, nullable=False)

    # --- Новое: состояние эволюции/сезонных эффектов и последний тик эволюции ---
    eco_json        = db.Column(db.Text, nullable=True)              # внутреннее состояние (гистерезисы и т.п.)
    last_evolve_ts  = db.Column(db.Float, nullable=False, default=0) # когда последний раз применяли эволюцию

    __table_args__ = (UniqueConstraint('cx','cy', name='uq_world_chunks_cx_cy'),)

    # Удобные хелперы (не обязательны к использованию, но удобно)
    def tiles_matrix(self):
        try:
            return json.loads(self.tiles_json)
        except Exception:
            return []

    def set_tiles_matrix(self, matrix):
        self.tiles_json = json.dumps(matrix, separators=(",",":"))

    def climate_dict(self):
        try:
            return json.loads(self.climate_json)
        except Exception:
            return {}


class WorldBuilding(db.Model):
    __tablename__ = "world_buildings"
    id = db.Column(db.Integer, primary_key=True)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(24), nullable=False)  # "camp" | "town" | "tavern" | "road"
    owner_id = db.Column(db.String(64))
    data_json = db.Column(db.Text, default="{}")
    created_at = db.Column(db.Float, nullable=False)
    __table_args__ = (UniqueConstraint('x','y', name='uq_world_buildings_xy'),)


class WorldOverride(db.Model):
    """
    Оверрайд базового тайла (админ/ивенты). Если запись есть — заменяем базовый тайл на tile_id.
    """
    __tablename__ = "world_overrides"
    id = db.Column(db.Integer, primary_key=True)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    tile_id = db.Column(db.String(24), nullable=False)   # "sand"|"forest"|...
    reason = db.Column(db.String(120))
    author_id = db.Column(db.String(64))
    created_at = db.Column(db.Float, nullable=False)
    __table_args__ = (UniqueConstraint('x','y', name='uq_world_overrides_xy'),)


class WorldMonster(db.Model):
    __tablename__ = "world_monsters"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, index=True)
    x = db.Column(db.Integer, nullable=False)
    y = db.Column(db.Integer, nullable=False)
    biome = db.Column(db.String(32), nullable=False)
    kind = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    template_key = db.Column(db.String(48), nullable=False, default="generic")
    level = db.Column(db.Integer, nullable=False)
    is_boss = db.Column(db.Boolean, nullable=False, default=False)
    hp = db.Column(db.Integer, nullable=False)
    hp_max = db.Column(db.Integer, nullable=False)
    attack = db.Column(db.Integer, nullable=False)
    defense = db.Column(db.Integer, nullable=False)
    agility = db.Column(db.Integer, nullable=False)
    xp_reward = db.Column(db.Integer, nullable=False)
    gold_reward = db.Column(db.Integer, nullable=False, default=0)
    state = db.Column(db.String(16), nullable=False, default="idle")
    data_json = db.Column(db.Text, nullable=False, default="{}")
    spawned_at = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.Float, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', 'x', 'y', name='uq_world_monster_user_xy'),
    )


class WorldCombat(db.Model):
    __tablename__ = "world_combat"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(64), nullable=False, unique=True, index=True)
    monster_id = db.Column(db.Integer, db.ForeignKey("world_monsters.id"), nullable=False)
    monster = db.relationship("WorldMonster", lazy="joined")
    player_hp = db.Column(db.Integer, nullable=False)
    player_hp_max = db.Column(db.Integer, nullable=False)
    turn = db.Column(db.Integer, nullable=False, default=1)
    log_json = db.Column(db.Text, nullable=False, default="[]")
    state = db.Column(db.String(16), nullable=False, default="active")
    started_at = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.Float, nullable=False)

    __table_args__ = (
        UniqueConstraint('user_id', name='uq_world_combat_user'),
    )


def ensure_world_models():
    db.create_all()
