# routes_craft.py - API для системы крафта
from flask import Blueprint, jsonify, request, g
from accounts.models import ItemDef, inventory_totals
from craft_models import (
    CraftRecipe, 
    ensure_craft_models,
    check_craft_requirements,
    start_craft,
    complete_craft,
    get_craft_status
)

bp = Blueprint("craft_api", __name__, url_prefix="/craft/api")


def _serialize_recipe(recipe: CraftRecipe) -> dict:
    """Сериализует рецепт для API"""
    components = recipe.components()
    
    # Обогащаем компоненты информацией о предметах
    enriched_components = []
    for comp in components:
        item = ItemDef.query.filter_by(key=comp.get("key", "")).first()
        enriched_components.append({
            "key": comp.get("key", ""),
            "qty": comp.get("qty", 0),
            "name": item.name if item else comp.get("key", ""),
            "icon": f"/static/icons/items/{item.icon}.png" if item and item.icon else None
        })
    
    # Информация о результате
    result_item = ItemDef.query.filter_by(key=recipe.result_item_key).first()
    
    return {
        "key": recipe.key,
        "name": recipe.name,
        "description": recipe.description,
        "category": recipe.category,
        "craft_time_sec": recipe.craft_time_sec,
        "min_level": recipe.min_level,
        "components": enriched_components,
        "result": {
            "key": recipe.result_item_key,
            "qty": recipe.result_qty,
            "name": result_item.name if result_item else recipe.result_item_key,
            "icon": f"/static/icons/items/{result_item.icon}.png" if result_item and result_item.icon else None
        }
    }


@bp.get("/recipes")
def api_recipes():
    """Возвращает все доступные рецепты"""
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    
    ensure_craft_models()
    
    # Группируем по категориям
    recipes = CraftRecipe.query.order_by(CraftRecipe.category.asc(), CraftRecipe.name.asc()).all()
    
    categories = {}
    for recipe in recipes:
        cat = recipe.category
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(_serialize_recipe(recipe))
    
    return jsonify({
        "ok": True,
        "categories": categories,
        "total_recipes": len(recipes)
    })


@bp.get("/recipe/<recipe_key>")
def api_recipe_details(recipe_key: str):
    """Детали конкретного рецепта с проверкой доступности"""
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    
    recipe = CraftRecipe.query.filter_by(key=recipe_key).first()
    if not recipe:
        return jsonify({"ok": False, "error": "recipe_not_found"}), 404
    
    # Проверяем требования
    can_craft, msg, _ = check_craft_requirements(g.user.id, recipe_key)
    
    recipe_data = _serialize_recipe(recipe)
    recipe_data["can_craft"] = can_craft
    recipe_data["craft_error"] = msg if not can_craft else None
    
    return jsonify({
        "ok": True,
        "recipe": recipe_data
    })


@bp.post("/start")
def api_start_craft():
    """Начинает крафт"""
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    
    data = request.get_json(silent=True) or {}
    recipe_key = (data.get("recipe_key") or "").strip()
    
    if not recipe_key:
        return jsonify({"ok": False, "error": "recipe_key_required"}), 400
    
    success, message, session_id = start_craft(g.user.id, recipe_key)
    
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    
    # Возвращаем статус крафта
    status = get_craft_status(g.user.id)
    totals = inventory_totals(g.user.id)
    
    return jsonify({
        "ok": True,
        "message": "Крафт начат",
        "session_id": session_id,
        "craft_status": status,
        "inventory_totals": totals
    })


@bp.post("/complete")
def api_complete_craft():
    """Завершает готовый крафт"""
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    
    success, message, result_item_key = complete_craft(g.user.id)
    
    if not success:
        return jsonify({"ok": False, "error": message}), 400
    
    # Информация о созданном предмете
    result_item = ItemDef.query.filter_by(key=result_item_key).first()
    totals = inventory_totals(g.user.id)
    
    return jsonify({
        "ok": True,
        "message": "Крафт завершен",
        "result": {
            "key": result_item_key,
            "name": result_item.name if result_item else result_item_key,
            "icon": f"/static/icons/items/{result_item.icon}.png" if result_item and result_item.icon else None
        },
        "inventory_totals": totals
    })


@bp.get("/status")
def api_craft_status():
    """Возвращает статус текущего крафта"""
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    
    status = get_craft_status(g.user.id)
    
    return jsonify({
        "ok": True,
        "craft_status": status,
        "has_active_craft": status is not None
    })


@bp.post("/cancel")
def api_cancel_craft():
    """Отменяет текущий крафт (возвращает ресурсы)"""
    if not getattr(g, "user", None):
        return jsonify({"ok": False, "error": "auth_required"}), 401
    
    from craft_models import CraftSession
    
    session = CraftSession.query.filter_by(user_id=g.user.id, status="crafting").first()
    if not session:
        return jsonify({"ok": False, "error": "no_active_craft"}), 400
    
    # Получаем рецепт и возвращаем ресурсы
    recipe = CraftRecipe.query.get(session.recipe_id)
    if recipe:
        from accounts.models import give_item
        components = recipe.components()
        for comp in components:
            give_item(g.user.id, comp.get("key", ""), comp.get("qty", 0))
    
    # Отменяем сессию
    session.status = "cancelled"
    from models import db
    db.session.add(session)
    db.session.commit()
    
    totals = inventory_totals(g.user.id)
    
    return jsonify({
        "ok": True,
        "message": "Крафт отменен, ресурсы возвращены",
        "inventory_totals": totals
    })