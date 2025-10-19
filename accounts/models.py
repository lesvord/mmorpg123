import time
import json
from typing import Optional, Dict, Tuple, List, Union

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import UniqueConstraint, ForeignKey, Index, event, and_
from sqlalchemy.orm import relationship, mapped_column, Mapped

# ВАЖНО: это глобальный объект БД из вашего корневого модуля models.py
from models import db


# ==========================
# Пользователь / Аккаунт
# ==========================
class User(db.Model):
    __tablename__ = "acc_users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Основные идентификаторы
    email:    Mapped[str] = mapped_column(db.String(120), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(db.String(40),  unique=True, index=True, nullable=False)

    # Пароль (для логина по паре email/пароль). Может быть пустым, если вход только через Telegram.
    pw_hash:  Mapped[str] = mapped_column(db.String(255), nullable=False, default="")

    # Опциональные поля Telegram-авторизации
    tg_id:        Mapped[Optional[str]] = mapped_column(db.String(32), unique=True, index=True, nullable=True)
    tg_username:  Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)

    created_at:    Mapped[float] = mapped_column(db.Float, nullable=False, default=lambda: time.time())
    last_login_at: Mapped[float] = mapped_column(db.Float, nullable=False, default=lambda: time.time())

    # Связи
    profile = relationship(
        "PlayerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="joined",
    )
    inventory = relationship(
        "InventoryItem",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # Утилиты
    def set_password(self, pw: str):
        self.pw_hash = generate_password_hash(pw or "")

    def check_password(self, pw: str) -> bool:
        try:
            return bool(self.pw_hash) and check_password_hash(self.pw_hash, pw or "")
        except Exception:
            return False

    def touch_login(self):
        self.last_login_at = time.time()

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} email={self.email!r}>"


# ==========================
# Профиль / Параметры игрока
# ==========================
class PlayerProfile(db.Model):
    __tablename__ = "acc_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("acc_users.id"), primary_key=True)

    # Прогресс
    level: Mapped[int] = mapped_column(db.Integer, default=1, nullable=False)
    xp:    Mapped[int] = mapped_column(db.Integer, default=0, nullable=False)

    # Основные статы
    str_: Mapped[int] = mapped_column("str", db.Integer, default=5, nullable=False)
    agi:  Mapped[int] = mapped_column(db.Integer, default=5, nullable=False)
    int_: Mapped[int] = mapped_column("int", db.Integer, default=5, nullable=False)
    vit:  Mapped[int] = mapped_column(db.Integer, default=5, nullable=False)
    defense: Mapped[int] = mapped_column(db.Integer, default=5, nullable=False)
    luck: Mapped[int] = mapped_column(db.Integer, default=1, nullable=False)

    stamina_max: Mapped[int] = mapped_column(db.Integer, default=100, nullable=False)
    gold:        Mapped[int] = mapped_column(db.Integer, default=0,   nullable=False)

    # Новое: базовая грузоподъёмность, кг (можно потом растить перками/сумками)
    carry_capacity_kg: Mapped[float] = mapped_column(db.Float, default=30.0, nullable=False)

    # Визуал
    avatar_url:  Mapped[Optional[str]] = mapped_column(db.String(240), nullable=True)

    user = relationship("User", back_populates="profile", lazy="joined")

    # Простая кривая опыта: до след. уровня
    def xp_to_next(self) -> int:
        # Пример: квадратичная прогрессия
        return int(50 + (self.level ** 2) * 10)

    def add_xp(self, amount: int) -> Tuple[int, int]:
        """
        Добавляет XP. Возвращает (уровень_до, уровень_после).
        """
        before = self.level
        self.xp = max(0, int(self.xp) + max(0, int(amount)))
        while self.xp >= self.xp_to_next():
            self.xp -= self.xp_to_next()
            self.level += 1
            # Пассивный рост статов/выносливости
            self.vit += 1
            self.str_ += 1
            self.agi += 1
            self.defense += 1
            self.stamina_max += 5
        return before, self.level

    def add_gold(self, amount: int):
        self.gold = max(0, int(self.gold) + int(amount))

    def as_dict(self) -> Dict[str, Union[int, float]]:
        return {
            "lvl": self.level,
            "xp": self.xp,
            "xp_to_next": self.xp_to_next(),
            "str": self.str_,
            "agi": self.agi,
            "int": self.int_,
            "vit": self.vit,
            "defense": self.defense,
            "luck": self.luck,
            "stamina_max": self.stamina_max,
            "gold": self.gold,
            "carry_capacity_kg": float(self.carry_capacity_kg or 30.0),
        }

    # Базовые боевые характеристики с учётом текущих статов
    def combat_snapshot(self, load_totals: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        load_frac = 0.0
        if load_totals:
            try:
                load_frac = max(0.0, float(load_totals.get("load_frac", 0.0)))
            except Exception:
                load_frac = 0.0

        encumber_pen = min(0.4, load_frac * 0.45)
        level = max(1, int(self.level or 1))
        str_base = max(1, int(self.str_ or 1))
        agi_base = max(1, int(self.agi or 1))
        def_base = max(1, int(self.defense or self.vit or 1))
        vit_base = max(1, int(self.vit or 1))
        luck = max(0, int(self.luck or 0))

        hp_max = int(60 + vit_base * 12 + str_base * 1.8 + level * 8)
        attack = float(str_base * (1.8 + level * 0.08))
        defense = float(def_base * (1.3 + level * 0.05))
        agility = float(agi_base * (1.1 + level * 0.04)) * (1.0 - encumber_pen * 0.5)

        crit = 0.05 + agi_base * 0.003 + luck * 0.004
        dodge = (0.04 + agi_base * 0.0035) * (1.0 - encumber_pen)
        speed = 1.0 + agi_base * 0.015 - encumber_pen * 0.35

        crit = max(0.03, min(0.45, crit))
        dodge = max(0.01, min(0.35, dodge))
        speed = max(0.5, min(2.2, speed))

        return {
            "level": level,
            "hp_max": hp_max,
            "attack": round(attack, 1),
            "defense": round(defense, 1),
            "agility": round(agility, 1),
            "crit": round(crit, 3),
            "dodge": round(dodge, 3),
            "speed": round(speed, 3),
            "encumber_pen": round(encumber_pen, 3),
        }

    def __repr__(self) -> str:
        return f"<Profile user_id={self.user_id} lvl={self.level} xp={self.xp}>"


# ==========================
# Справочник предметов
# ==========================
class ItemDef(db.Model):
    __tablename__ = "acc_item_defs"

    id:   Mapped[int] = mapped_column(primary_key=True)
    key:  Mapped[str] = mapped_column(db.String(64), unique=True, index=True, nullable=False)  # "sword_wood"
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)

    # "weapon","armor","consumable","trinket","resource","material",...
    type: Mapped[str] = mapped_column(db.String(24),  nullable=False)

    # Если предмет экипируется — в какой слот: "weapon","head","chest","ring","amulet",...
    slot: Mapped[Optional[str]] = mapped_column(db.String(24), nullable=True)

    rarity: Mapped[str] = mapped_column(db.String(16), default="common", nullable=False)
    icon:   Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)

    # JSON с бонусами статов/эффектами
    stats_json: Mapped[str] = mapped_column(db.Text, default="{}")

    # Новое: физический вес (в кг) и макс. размер стака
    weight_kg: Mapped[float] = mapped_column(db.Float, default=0.0, nullable=False)
    stack_max: Mapped[int]   = mapped_column(db.Integer, default=99,  nullable=False)

    # Индекс по (type, slot) для быстрых выборок
    __table_args__ = (
        Index("ix_item_type_slot", "type", "slot"),
    )

    def stats(self) -> Dict[str, float]:
        try:
            obj = json.loads(self.stats_json or "{}")
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}

    def __repr__(self) -> str:
        return f"<ItemDef {self.key} type={self.type} slot={self.slot}>"


# ==========================
# Инвентарь пользователя
# ==========================
class InventoryItem(db.Model):
    __tablename__ = "acc_inventory"

    id:      Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("acc_users.id"), index=True, nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("acc_item_defs.id"), nullable=False)

    qty:      Mapped[int]  = mapped_column(db.Integer, default=1, nullable=False)
    equipped: Mapped[bool] = mapped_column(db.Boolean, default=False, nullable=False)
    # Фактический слот, в который экипировано (на случай предметов с несколькими возможными слотами)
    slot:     Mapped[Optional[str]] = mapped_column(db.String(24), nullable=True)

    user = relationship("User", back_populates="inventory", lazy="joined")
    item = relationship("ItemDef", lazy="joined")

    # Ограничение уникальности помогает избегать дубликатов «одинаковых состояний»
    __table_args__ = (
        UniqueConstraint('user_id', 'item_id', 'equipped', 'slot', name='uq_inv_user_item_slot'),
        Index("ix_inv_user_equipped", "user_id", "equipped"),
    )

    # ----- Бизнес-логика экипировки -----
    def can_equip_here(self) -> Tuple[bool, str]:
        """
        Проверяет, можно ли экипировать этот предмет в self.slot (или в item.slot, если self.slot пуст).
        """
        if not self.item:
            return False, "unknown_item"
        base_slot = self.item.slot
        if not base_slot:
            return False, "not_equipable"
        target_slot = self.slot or base_slot
        return True, target_slot

    def equip(self) -> Tuple[bool, str]:
        """
        Экипирует предмет. Снимает другие предметы в этом слоте у пользователя.
        Возвращает (ok, message).
        """
        ok, target_slot = self.can_equip_here()
        if not ok:
            return False, target_slot  # код ошибки

        # Снимаем остальные предметы в этом слоте
        db.session.query(InventoryItem).filter(
            and_(
                InventoryItem.user_id == self.user_id,
                InventoryItem.equipped.is_(True),
                InventoryItem.id != self.id,
                InventoryItem.slot == target_slot,
            )
        ).update({"equipped": False}, synchronize_session=False)

        # Помечаем текущий как экипированный
        self.equipped = True
        self.slot = target_slot
        db.session.add(self)
        return True, "equipped"

    def unequip(self) -> Tuple[bool, str]:
        if not self.equipped:
            return False, "already_unequipped"
        self.equipped = False
        db.session.add(self)
        return True, "unequipped"

    def __repr__(self) -> str:
        return f"<InvItem id={self.id} user={self.user_id} item={self.item_id} eq={self.equipped} slot={self.slot}>"


# ===========================================================
# Утилиты инвентаря/веса/выдачи
# ===========================================================
def _item_weight_kg(item: ItemDef) -> float:
    """
    Унифицированно читаем вес предмета.
    Приоритет: явное поле weight_kg → stats_json["w"] → 0.
    """
    try:
        if item and item.weight_kg is not None:
            return float(item.weight_kg)
    except Exception:
        pass
    try:
        w = (item.stats() or {}).get("w")
        return float(w) if w is not None else 0.0
    except Exception:
        return 0.0


def inventory_weight_kg(user_id: int) -> float:
    """
    Считает суммарный вес инвентаря (без учёта экипированных слотов — при желании можно корректировать).
    """
    total = 0.0
    rows: List[InventoryItem] = InventoryItem.query.filter_by(user_id=user_id).all()
    for r in rows:
        if not r.item:
            continue
        total += _item_weight_kg(r.item) * max(0, int(r.qty or 0))
    return round(total, 3)


def carry_capacity_kg(user_id: int) -> float:
    prof = PlayerProfile.query.get(user_id)
    cap = float(prof.carry_capacity_kg if prof and prof.carry_capacity_kg is not None else 30.0)
    return round(cap, 3)


def _load_profile(frac: float) -> Tuple[str, str]:
    """
    Возвращает (tier, description) для UI/геймплея исходя из доли загрузки.
    """
    if frac <= 0.45:
        return "light", "Нагрузка почти не ощущается"
    if frac <= 0.75:
        return "steady", "Чувствуется тяжесть, но темп держится"
    if frac <= 1.05:
        return "strained", "Переутомление накапливается, скорость падает"
    if frac <= 1.25:
        return "overloaded", "Вы почти перегружены, движение даётся с трудом"
    return "encumbered", "Перегруз: придётся замедлиться или разгрузиться"


def inventory_totals(user_id: int) -> Dict[str, float]:
    w = inventory_weight_kg(user_id)
    cap = carry_capacity_kg(user_id)
    if cap <= 0:
        load_frac = 0.0
    else:
        load_frac = max(0.0, w / cap)

    pct = min(160.0, round(load_frac * 100.0, 2))

    # Немного «реализма»: после половины вместимости появляются штрафы к скорости,
    # а после перегруза растёт и усталость от любых действий.
    load_clamped = min(1.6, load_frac)
    speed_mul = 1.0 - 0.38 * (load_clamped ** 1.35)
    speed_mul = max(0.28, round(speed_mul, 3))

    fatigue_mul = 1.0 + 0.65 * (load_clamped ** 1.45)
    fatigue_mul = round(fatigue_mul, 3)

    tier, desc = _load_profile(load_frac)

    return {
        "weight_kg": round(w, 3),
        "capacity_kg": round(cap, 3),
        "load_pct": pct,
        "load_frac": round(load_frac, 3),
        "speed_mul": speed_mul,
        "fatigue_mul": fatigue_mul,
        "tier": tier,
        "tier_desc": desc,
        "over_encumbered": load_frac > 1.0,
    }


def list_inventory(user_id: int) -> List[InventoryItem]:
    """
    Возвращает инвентарь пользователя (как есть, с джойном ItemDef).
    """
    return InventoryItem.query.filter_by(user_id=user_id).order_by(InventoryItem.id.asc()).all()


def _is_stackable(item: ItemDef) -> bool:
    """
    Простое правило стэкинга: всё, что НЕ экипируемое (slot is None) и не уникальное — стэкается.
    """
    if not item:
        return False
    if item.slot:
        return False
    # типы, которые обычно стэкаются
    return item.type in ("resource", "material", "consumable", "ingredient", "loot")


def give_item(user_id: int, item_key: str, qty: int = 1, auto_equip: bool = False) -> Tuple[bool, str, Optional[int]]:
    """
    Выдаёт пользователю предмет по ключу справочника.
    - учитывает стэкинг (qty увеличивает существующую стопку)
    - проверяет перегруз до добавления
    Возвращает (ok, message, inv_id|None).
    """
    item = ItemDef.query.filter_by(key=item_key).first()
    if not item:
        return False, "item_not_found", None

    qty = max(1, int(qty))
    add_weight = _item_weight_kg(item) * qty
    cur_w = inventory_weight_kg(user_id)
    cap = carry_capacity_kg(user_id)
    if cur_w + add_weight > cap + 1e-9:
        return False, "overweight", None

    inv_id: Optional[int] = None
    if _is_stackable(item):
        # ищем существующую «обычную» стопку (equipped=False, slot=NULL)
        row = InventoryItem.query.filter_by(user_id=user_id, item_id=item.id, equipped=False, slot=None).first()
        if row:
            row.qty = max(0, int(row.qty or 0)) + qty
            db.session.add(row)
            db.session.commit()
            inv_id = row.id
        else:
            row = InventoryItem(user_id=user_id, item_id=item.id, qty=qty, equipped=False, slot=None)
            db.session.add(row)
            db.session.commit()
            inv_id = row.id
    else:
        row = InventoryItem(user_id=user_id, item_id=item.id, qty=qty, equipped=False, slot=item.slot)
        db.session.add(row)
        db.session.commit()
        inv_id = row.id

    if auto_equip and item.slot:
        # экипируем только 1 шт.
        row.qty = max(1, int(row.qty or 1))
        ok, msg = row.equip()
        db.session.add(row)
        db.session.commit()
        return ok, msg, inv_id

    return True, "granted", inv_id


def drop_item(user_id: int, inv_id: int, qty: int = 1) -> Tuple[bool, str]:
    """
    Выбрасывает qty из записи инвентаря. Если qty >= текущему количеству — удаляем запись.
    """
    row = InventoryItem.query.filter_by(id=inv_id, user_id=user_id).first()
    if not row:
        return False, "not_found"
    if row.equipped:
        return False, "cant_drop_equipped"
    q = max(1, int(qty))
    if (row.qty or 0) <= q:
        db.session.delete(row)
    else:
        row.qty = int(row.qty) - q
        db.session.add(row)
    db.session.commit()
    return True, "dropped"


def equipped_by_slot(user_id: int) -> Dict[str, InventoryItem]:
    """
    Возвращает словарь {slot -> InventoryItem}, где предметы экипированы.
    """
    rows = InventoryItem.query.filter_by(user_id=user_id, equipped=True).all()
    out: Dict[str, InventoryItem] = {}
    for r in rows:
        s = r.slot or (r.item.slot if r.item else None)
        if s:
            out[s] = r
    return out


# ===========================================================
# Инициализация/миграции и сиды
# ===========================================================
def ensure_accounts_models():
    """
    Создаёт таблицы и выполняет мягкие миграции для уже существующей SQLite-БД.
    Работает без Alembic, только для простых апдейтов.
    """
    # Сначала создаём то, чего нет вообще (по текущим моделям)
    db.create_all()

    eng = db.engine
    if eng.dialect.name != "sqlite":
        # Для продакшена и других СУБД используйте Alembic.
        return

    def has_col(table: str, col: str) -> bool:
        # PRAGMA table_info возвращает: (cid, name, type, notnull, dflt_value, pk)
        with eng.connect() as conn:
            res = conn.exec_driver_sql(f'PRAGMA table_info("{table}")')
            cols = [row[1] for row in res.fetchall()]
            return col in cols

    # Выполняем DDL/индексы
    with eng.begin() as conn:
        # --- acc_users: новые поля уже выше добавлялись в другом месте проекта ---

        # --- acc_profiles: грузоподъёмность ---
        if not has_col("acc_profiles", "carry_capacity_kg"):
            conn.exec_driver_sql('ALTER TABLE acc_profiles ADD COLUMN carry_capacity_kg REAL DEFAULT 30')

        # --- acc_profiles: защита ---
        if not has_col("acc_profiles", "defense"):
            conn.exec_driver_sql('ALTER TABLE acc_profiles ADD COLUMN defense INTEGER DEFAULT 5')

        # --- acc_item_defs: вес и стек ---
        if not has_col("acc_item_defs", "weight_kg"):
            conn.exec_driver_sql('ALTER TABLE acc_item_defs ADD COLUMN weight_kg REAL DEFAULT 0')
        if not has_col("acc_item_defs", "stack_max"):
            conn.exec_driver_sql('ALTER TABLE acc_item_defs ADD COLUMN stack_max INTEGER DEFAULT 99')

        # --- индексы, заявленные в моделях ---
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_item_type_slot "
            "ON acc_item_defs(type, slot)"
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_inv_user_item_slot "
            "ON acc_inventory(user_id, item_id, equipped, slot)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_inv_user_equipped "
            "ON acc_inventory(user_id, equipped)"
        )


def seed_default_items():
    """
    Идемпотентно добавляет базовые предметы, если отсутствуют.
    Расширено: добавлены ресурсы с весом и стэком.
    """
    defaults = [
        # Базовое снаряжение
        dict(key="sword_wood", name="Деревянный меч", type="weapon", slot="weapon",
             rarity="common", icon="sword_wood", stats={"atk": 2}, weight_kg=1.2, stack_max=1),
        dict(key="cap_cloth",  name="Тряпичная шапка", type="armor",  slot="head",
             rarity="common", icon="cap_cloth",  stats={"def": 1}, weight_kg=0.3, stack_max=1),
        dict(key="boots_leather", name="Кожаные сапоги", type="armor", slot="feet",
             rarity="common", icon="boots_leather", stats={"agi": 1}, weight_kg=0.9, stack_max=1),
        dict(key="potion_small", name="Малое зелье", type="consumable", slot=None,
             rarity="common", icon="potion_small", stats={"heal": 20}, weight_kg=0.25, stack_max=20),

        # Ресурсы (стэкаются, вес есть)
        dict(key="res_wood_log", name="Бревно", type="resource", slot=None,
             rarity="common", icon="wood_log", stats={"res": True}, weight_kg=2.0, stack_max=20),
        dict(key="res_stick", name="Палка", type="resource", slot=None,
             rarity="common", icon="stick", stats={"res": True}, weight_kg=0.2, stack_max=50),
        dict(key="res_stone", name="Камень", type="resource", slot=None,
             rarity="common", icon="stone", stats={"res": True}, weight_kg=1.0, stack_max=50),
        dict(key="res_iron_ore", name="Железная руда", type="resource", slot=None,
             rarity="uncommon", icon="iron_ore", stats={"res": True}, weight_kg=1.5, stack_max=50),
        dict(key="res_berries", name="Ягоды", type="resource", slot=None,
             rarity="common", icon="berries", stats={"res": True, "food": 2}, weight_kg=0.2, stack_max=50),
        dict(key="res_herb", name="Трава", type="resource", slot=None,
             rarity="common", icon="herb", stats={"res": True, "alch": 1}, weight_kg=0.05, stack_max=99),
        dict(key="res_clay", name="Глина", type="resource", slot=None,
             rarity="common", icon="clay", stats={"res": True}, weight_kg=1.2, stack_max=50),
        dict(key="res_peat", name="Торф", type="resource", slot=None,
             rarity="common", icon="peat", stats={"res": True}, weight_kg=0.8, stack_max=50),
        dict(key="res_fish", name="Рыба", type="resource", slot=None,
             rarity="uncommon", icon="fish", stats={"res": True, "food": 5}, weight_kg=0.7, stack_max=20),
        dict(key="res_ice", name="Лёд/Снег", type="resource", slot=None,
             rarity="common", icon="ice", stats={"res": True}, weight_kg=0.5, stack_max=50),
        dict(key="res_sand", name="Песок", type="resource", slot=None,
             rarity="common", icon="sand", stats={"res": True}, weight_kg=1.0, stack_max=50),
        dict(key="res_fiber", name="Волокно", type="resource", slot=None,
             rarity="common", icon="fiber", stats={"res": True}, weight_kg=0.05, stack_max=99),
        dict(key="res_mushroom", name="Грибы", type="resource", slot=None,
             rarity="common", icon="mushroom", stats={"res": True, "food": 3}, weight_kg=0.15, stack_max=50),
        dict(key="res_reed", name="Камыш", type="resource", slot=None,
             rarity="common", icon="reed", stats={"res": True}, weight_kg=0.2, stack_max=50),
        dict(key="res_copper_ore", name="Медная руда", type="resource", slot=None,
             rarity="uncommon", icon="copper_ore", stats={"res": True}, weight_kg=1.4, stack_max=50),
        dict(key="res_gold_nug", name="Золотой самородок", type="resource", slot=None,
             rarity="rare", icon="gold_nug", stats={"res": True}, weight_kg=0.5, stack_max=20),
        dict(key="res_gem", name="Драгоценный камень", type="resource", slot=None,
             rarity="rare", icon="gem", stats={"res": True}, weight_kg=0.3, stack_max=20),
        dict(key="res_cactus", name="Кактус", type="resource", slot=None,
             rarity="common", icon="cactus", stats={"res": True}, weight_kg=1.2, stack_max=20),
        dict(key="res_obsidian", name="Обсидиан", type="resource", slot=None,
             rarity="uncommon", icon="obsidian", stats={"res": True}, weight_kg=2.0, stack_max=20),
    ]

    created = 0
    for d in defaults:
        row = ItemDef.query.filter_by(key=d["key"]).first()
        if row:
            # аккуратно обновим вес/стэк, если появились
            changed = False
            w = float(d.get("weight_kg", 0.0))
            sm = int(d.get("stack_max", 99))
            if (row.weight_kg or 0.0) != w:
                row.weight_kg = w
                changed = True
            if (row.stack_max or 99) != sm:
                row.stack_max = sm
                changed = True
            if changed:
                db.session.add(row)
            continue

        row = ItemDef(
            key=d["key"], name=d["name"], type=d["type"], slot=d.get("slot"),
            rarity=d["rarity"], icon=d.get("icon"),
            stats_json=json.dumps(d.get("stats") or {}, separators=(",", ":")),
            weight_kg=float(d.get("weight_kg", 0.0)),
            stack_max=int(d.get("stack_max", 99)),
        )
        db.session.add(row)
        created += 1
    if created:
        db.session.commit()
    return created


# ===========================================================
# Автосоздание профиля при создании пользователя
# ===========================================================
@event.listens_for(User, "after_insert")
def _create_profile(mapper, connection, target: User):
    # Автопрофиль с дефолтными статами
    connection.execute(
        db.text(
            "INSERT INTO acc_profiles (user_id, level, xp, str, agi, int, vit, luck, stamina_max, gold, carry_capacity_kg) "
            "VALUES (:uid, 1, 0, 5, 5, 5, 5, 1, 100, 0, 30)"
        ),
        dict(uid=target.id)
    )
