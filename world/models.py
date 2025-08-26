import time
import json
from typing import Optional, Dict, Any
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from models import db


class PlayerWorldState(db.Model):
    """
    Персональное состояние мира игрока.
    Ключ: user_id (FK -> acc_users.id)
    """
    __tablename__ = "world_player_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("acc_users.id"), primary_key=True)

    # Позиция и усталость
    pos_x: Mapped[int]   = mapped_column(db.Integer, default=0, nullable=False)
    pos_y: Mapped[int]   = mapped_column(db.Integer, default=0, nullable=False)
    fatigue: Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)

    # Активный план движения (если есть) — храним компактно
    plan_json: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)  # {"dirs":"URDL..","idx":0,"step_t":0.6}
    # Состояние лагеря
    camp_x: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    camp_y: Mapped[Optional[int]] = mapped_column(db.Integer, nullable=True)
    camp_owner: Mapped[bool]      = mapped_column(db.Boolean, default=False, nullable=False)

    updated_at: Mapped[float] = mapped_column(db.Float, default=lambda: time.time(), nullable=False)

    # на будущее — инвентарь/открытые тайлы/видимость и т.п.
    misc_json: Mapped[Optional[str]] = mapped_column(db.Text, nullable=True)

    __table_args__ = (
        Index("ix_world_state_pos", "pos_x", "pos_y"),
    )

    def plan_dict(self) -> Dict[str, Any]:
        try:
            return json.loads(self.plan_json) if self.plan_json else {}
        except Exception:
            return {}

    def set_plan(self, plan: Optional[Dict[str, Any]]):
        self.plan_json = json.dumps(plan or {}, separators=(",", ":")) if plan else None

    def misc_dict(self) -> Dict[str, Any]:
        try:
            return json.loads(self.misc_json) if self.misc_json else {}
        except Exception:
            return {}


def get_or_create_state(user_id: int) -> PlayerWorldState:
    st = PlayerWorldState.query.get(user_id)
    if st:
        return st
    st = PlayerWorldState(user_id=user_id, pos_x=0, pos_y=0, fatigue=0, updated_at=time.time())
    db.session.add(st)
    db.session.commit()
    return st


def save_state(st: PlayerWorldState):
    st.updated_at = time.time()
    db.session.add(st)
    db.session.commit()
