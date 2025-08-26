# craft_models.py - Система крафта
import json
import time
from typing import Dict, List, Optional, Tuple
from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from models import db
from accounts.models import ItemDef, InventoryItem, give_item, drop_item


class CraftRecipe(db.Model):
    """
    Рецепт крафта: ресурсы -> результат
    """
    __tablename__ = "craft_recipes"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(db.String(64), unique=True, index=True, nullable=False)  # "craft_sword_wood"
    name: Mapped[str] = mapped_column(db.String(120), nullable=False)  # "Деревянный меч"
    
    # JSON массив компонентов: [{"key": "res_stick", "qty": 3}, {"key": "res_stone", "qty": 1}]
    components_json: Mapped[str] = mapped_column(db.Text, nullable=False)
    
    # Результат крафта
    result_item_key: Mapped[str] = mapped_column(db.String(64), nullable=False)  # "sword_wood"
    result_qty: Mapped[int] = mapped_column(db.Integer, default=1, nullable=False)
    
    # Категория для группировки в UI
    category: Mapped[str] = mapped_column(db.String(32), default="misc", nullable=False)  # "weapons", "tools", "armor"
    
    # Требования
    min_level: Mapped[int] = mapped_column(db.Integer, default=1, nullable=False)
    craft_time_sec: Mapped[float] = mapped_column(db.Float, default=2.0, nullable=False)
    
    # Метаданные
    icon: Mapped[Optional[str]] = mapped_column(db.String(64), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(db.String(240), nullable=True)
    created_at: Mapped[float] = mapped_column(db.Float, default=lambda: time.time(), nullable=False)

    __table_args__ = (
        Index("ix_craft_category", "category"),
    )

    def components(self) -> List[Dict[str, any]]:
        """Возвращает компоненты рецепта"""
        try:
            return json.loads(self.components_json or "[]")
        except Exception:
            return []

    def set_components(self, components: List[Dict[str, any]]):
        """Устанавливает компоненты рецепта"""
        self.components_json = json.dumps(components, separators=(",", ":"))


class CraftSession(db.Model):
    """
    Активная сессия крафта пользователя
    """
    __tablename__ = "craft_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("acc_users.id"), index=True, nullable=False)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("craft_recipes.id"), nullable=False)
    
    started_at: Mapped[float] = mapped_column(db.Float, default=lambda: time.time(), nullable=False)
    finish_at: Mapped[float] = mapped_column(db.Float, nullable=False)  # started_at + craft_time_sec
    
    # Статус: "crafting", "completed", "cancelled"
    status: Mapped[str] = mapped_column(db.String(16), default="crafting", nullable=False)

    __table_args__ = (
        Index("ix_craft_session_user_status", "user_id", "status"),
    )


def ensure_craft_models():
    """Создает таблицы крафта"""
    db.create_all()


def check_craft_requirements(user_id: int, recipe_key: str) -> Tuple[bool, str, Optional[CraftRecipe]]:
    """
    Проверяет возможность крафта:
    - рецепт существует
    - есть все ресурсы
    - нет активной сессии крафта
    """
    recipe = CraftRecipe.query.filter_by(key=recipe_key).first()
    if not recipe:
        return False, "recipe_not_found", None
    
    # Проверяем активную сессию
    active = CraftSession.query.filter_by(user_id=user_id, status="crafting").first()
    if active:
        return False, "already_crafting", None
    
    # Проверяем ресурсы
    components = recipe.components()
    for comp in components:
        item_key = comp.get("key", "")
        needed_qty = int(comp.get("qty", 0))
        
        # Находим предмет в инвентаре
        item_def = ItemDef.query.filter_by(key=item_key).first()
        if not item_def:
            return False, f"component_not_exists:{item_key}", None
            
        # Считаем количество в инвентаре
        inv_qty = db.session.query(db.func.sum(InventoryItem.qty)).filter(
            InventoryItem.user_id == user_id,
            InventoryItem.item_id == item_def.id,
            InventoryItem.equipped == False  # не экипированные
        ).scalar() or 0
        
        if inv_qty < needed_qty:
            return False, f"insufficient:{item_key}:{needed_qty}:{inv_qty}", None
    
    return True, "ok", recipe


def consume_craft_resources(user_id: int, recipe: CraftRecipe) -> bool:
    """
    Списывает ресурсы для крафта из инвентаря
    """
    try:
        components = recipe.components()
        for comp in components:
            item_key = comp.get("key", "")
            needed_qty = int(comp.get("qty", 0))
            
            item_def = ItemDef.query.filter_by(key=item_key).first()
            if not item_def:
                continue
                
            # Находим записи инвентаря с этим предметом
            inv_items = InventoryItem.query.filter(
                InventoryItem.user_id == user_id,
                InventoryItem.item_id == item_def.id,
                InventoryItem.equipped == False,
                InventoryItem.qty > 0
            ).order_by(InventoryItem.id.asc()).all()
            
            remaining = needed_qty
            for inv in inv_items:
                if remaining <= 0:
                    break
                    
                take = min(remaining, inv.qty)
                remaining -= take
                
                if inv.qty <= take:
                    db.session.delete(inv)
                else:
                    inv.qty -= take
                    db.session.add(inv)
        
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        print(f"Error consuming craft resources: {e}")
        return False


def start_craft(user_id: int, recipe_key: str) -> Tuple[bool, str, Optional[int]]:
    """
    Начинает крафт. Возвращает (success, message, session_id)
    """
    can_craft, msg, recipe = check_craft_requirements(user_id, recipe_key)
    if not can_craft:
        return False, msg, None
    
    # Списываем ресурсы
    if not consume_craft_resources(user_id, recipe):
        return False, "failed_to_consume_resources", None
    
    # Создаем сессию
    session = CraftSession(
        user_id=user_id,
        recipe_id=recipe.id,
        started_at=time.time(),
        finish_at=time.time() + recipe.craft_time_sec,
        status="crafting"
    )
    db.session.add(session)
    db.session.commit()
    
    return True, "craft_started", session.id


def complete_craft(user_id: int) -> Tuple[bool, str, Optional[str]]:
    """
    Завершает готовый крафт. Возвращает (success, message, result_item_key)
    """
    session = CraftSession.query.filter_by(user_id=user_id, status="crafting").first()
    if not session:
        return False, "no_active_craft", None
    
    # Проверяем время
    now = time.time()
    if now < session.finish_at:
        remaining = session.finish_at - now
        return False, f"not_ready:{remaining:.1f}", None
    
    # Получаем рецепт
    recipe = CraftRecipe.query.get(session.recipe_id)
    if not recipe:
        session.status = "cancelled"
        db.session.add(session)
        db.session.commit()
        return False, "recipe_missing", None
    
    # Выдаем результат
    ok, msg, inv_id = give_item(user_id, recipe.result_item_key, recipe.result_qty)
    if not ok:
        # Если не поместилось - возвращаем ресурсы
        components = recipe.components()
        for comp in components:
            give_item(user_id, comp.get("key", ""), comp.get("qty", 0))
        
        session.status = "cancelled"
        db.session.add(session)
        db.session.commit()
        return False, f"inventory_full:{msg}", None
    
    # Помечаем сессию завершенной
    session.status = "completed"
    db.session.add(session)
    db.session.commit()
    
    return True, "craft_completed", recipe.result_item_key


def get_craft_status(user_id: int) -> Optional[Dict]:
    """
    Возвращает статус текущего крафта или None
    """
    session = CraftSession.query.filter_by(user_id=user_id, status="crafting").first()
    if not session:
        return None
    
    recipe = CraftRecipe.query.get(session.recipe_id)
    now = time.time()
    
    return {
        "session_id": session.id,
        "recipe_key": recipe.key if recipe else "unknown",
        "recipe_name": recipe.name if recipe else "Неизвестно",
        "started_at": session.started_at,
        "finish_at": session.finish_at,
        "progress": min(1.0, (now - session.started_at) / (session.finish_at - session.started_at)),
        "remaining_sec": max(0, session.finish_at - now),
        "ready": now >= session.finish_at
    }


def seed_craft_recipes():
    """
    Добавляет базовые рецепты крафта
    """
    recipes = [
        # Инструменты
        {
            "key": "craft_axe_stone",
            "name": "Каменный топор",
            "components": [
                {"key": "res_stick", "qty": 2},
                {"key": "res_stone", "qty": 3}
            ],
            "result_item_key": "tool_axe_stone",
            "result_qty": 1,
            "category": "tools",
            "craft_time_sec": 5.0,
            "description": "Простой топор для рубки деревьев"
        },
        {
            "key": "craft_pickaxe_stone",
            "name": "Каменная кирка",
            "components": [
                {"key": "res_stick", "qty": 2},
                {"key": "res_stone", "qty": 3}
            ],
            "result_item_key": "tool_pickaxe_stone",
            "result_qty": 1,
            "category": "tools",
            "craft_time_sec": 5.0,
            "description": "Простая кирка для добычи руды"
        },
        
        # Оружие
        {
            "key": "craft_sword_stone",
            "name": "Каменный меч",
            "components": [
                {"key": "res_stick", "qty": 1},
                {"key": "res_stone", "qty": 4}
            ],
            "result_item_key": "weapon_sword_stone",
            "result_qty": 1,
            "category": "weapons",
            "craft_time_sec": 8.0,
            "description": "Грубый но эффективный меч"
        },
        {
            "key": "craft_spear_wood",
            "name": "Деревянное копье",
            "components": [
                {"key": "res_stick", "qty": 3},
                {"key": "res_stone", "qty": 1}
            ],
            "result_item_key": "weapon_spear_wood",
            "result_qty": 1,
            "category": "weapons",
            "craft_time_sec": 4.0,
            "description": "Длинное копье для боя"
        },
        
        # Броня
        {
            "key": "craft_helmet_leather",
            "name": "Кожаный шлем",
            "components": [
                {"key": "res_fiber", "qty": 8},
                {"key": "res_berries", "qty": 2}  # для дубления
            ],
            "result_item_key": "armor_helmet_leather",
            "result_qty": 1,
            "category": "armor",
            "craft_time_sec": 10.0,
            "description": "Простая защита головы"
        },
        
        # Еда
        {
            "key": "craft_stew_fish",
            "name": "Рыбный суп",
            "components": [
                {"key": "res_fish", "qty": 1},
                {"key": "res_mushroom", "qty": 2},
                {"key": "res_berries", "qty": 1}
            ],
            "result_item_key": "food_stew_fish",
            "result_qty": 1,
            "category": "food",
            "craft_time_sec": 3.0,
            "description": "Сытный суп восстанавливает здоровье"
        },
        
        # Материалы
        {
            "key": "craft_rope",
            "name": "Веревка",
            "components": [
                {"key": "res_fiber", "qty": 6}
            ],
            "result_item_key": "material_rope",
            "result_qty": 3,
            "category": "materials",
            "craft_time_sec": 2.0,
            "description": "Прочная веревка из волокна"
        },
        {
            "key": "craft_cloth",
            "name": "Ткань",
            "components": [
                {"key": "res_fiber", "qty": 10}
            ],
            "result_item_key": "material_cloth",
            "result_qty": 2,
            "category": "materials", 
            "craft_time_sec": 6.0,
            "description": "Грубая ткань для одежды"
        }
    ]
    
    created = 0
    for r in recipes:
        existing = CraftRecipe.query.filter_by(key=r["key"]).first()
        if existing:
            continue
            
        recipe = CraftRecipe(
            key=r["key"],
            name=r["name"],
            components_json=json.dumps(r["components"], separators=(",", ":")),
            result_item_key=r["result_item_key"],
            result_qty=r["result_qty"],
            category=r["category"],
            craft_time_sec=r["craft_time_sec"],
            description=r.get("description")
        )
        db.session.add(recipe)
        created += 1
    
    if created:
        db.session.commit()
        print(f"Created {created} craft recipes")
    
    return created


def seed_craft_items():
    """
    Добавляет предметы, которые создаются крафтом
    """
    from accounts.models import ItemDef
    
    craft_items = [
        # Инструменты
        {"key": "tool_axe_stone", "name": "Каменный топор", "type": "tool", "slot": "weapon",
         "rarity": "common", "stats": {"atk": 4, "tool_power": 2}, "weight_kg": 2.5, "stack_max": 1},
        {"key": "tool_pickaxe_stone", "name": "Каменная кирка", "type": "tool", "slot": "weapon", 
         "rarity": "common", "stats": {"atk": 3, "mining_power": 3}, "weight_kg": 2.8, "stack_max": 1},
         
        # Оружие
        {"key": "weapon_sword_stone", "name": "Каменный меч", "type": "weapon", "slot": "weapon",
         "rarity": "common", "stats": {"atk": 6}, "weight_kg": 3.0, "stack_max": 1},
        {"key": "weapon_spear_wood", "name": "Деревянное копье", "type": "weapon", "slot": "weapon",
         "rarity": "common", "stats": {"atk": 5, "reach": 1}, "weight_kg": 1.8, "stack_max": 1},
         
        # Броня
        {"key": "armor_helmet_leather", "name": "Кожаный шлем", "type": "armor", "slot": "head",
         "rarity": "common", "stats": {"def": 2}, "weight_kg": 0.8, "stack_max": 1},
         
        # Еда
        {"key": "food_stew_fish", "name": "Рыбный суп", "type": "consumable", "slot": None,
         "rarity": "common", "stats": {"heal": 30, "satiety": 15}, "weight_kg": 0.4, "stack_max": 10},
         
        # Материалы
        {"key": "material_rope", "name": "Веревка", "type": "material", "slot": None,
         "rarity": "common", "stats": {}, "weight_kg": 0.2, "stack_max": 20},
        {"key": "material_cloth", "name": "Ткань", "type": "material", "slot": None,
         "rarity": "common", "stats": {}, "weight_kg": 0.3, "stack_max": 15}
    ]
    
    created = 0
    for item_data in craft_items:
        existing = ItemDef.query.filter_by(key=item_data["key"]).first()
        if existing:
            continue
            
        item = ItemDef(
            key=item_data["key"],
            name=item_data["name"],
            type=item_data["type"],
            slot=item_data.get("slot"),
            rarity=item_data["rarity"],
            icon=item_data.get("icon"),
            stats_json=json.dumps(item_data.get("stats", {}), separators=(",", ":")),
            weight_kg=item_data["weight_kg"],
            stack_max=item_data["stack_max"]
        )
        db.session.add(item)
        created += 1
    
    if created:
        db.session.commit()
        print(f"Created {created} craft items")
    
    return created