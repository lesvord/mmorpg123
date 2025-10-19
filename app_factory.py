# app_factory.py
import os
import time
import traceback
import importlib
from typing import Optional, Dict
from hashlib import sha1

from flask import Flask, redirect, url_for, Response, request, jsonify, g
from models import db, init_db_config
from perf_logger import log, set_log_paths

# ЯВНЫЕ блюпринты (регистрируем здесь ровно один раз)
from routes_world_resources import bp as world_resources_bp     # url_prefix="/world"
from routes_world_combat import bp as world_combat_bp           # url_prefix="/world"
from routes_inventory import bp as inv_bp                      # url_prefix="/inv/api"
from routes_craft import bp as craft_bp                        # url_prefix="/craft/api"

# ----- Путь лога в папке проекта -----
PROJECT_LOG = os.path.join(os.getcwd(), "logs", "perf.jsonl")
try:
    os.makedirs(os.path.dirname(PROJECT_LOG), exist_ok=True)
    set_log_paths([PROJECT_LOG])
    print(f"[AppFactory] perf log -> {PROJECT_LOG}")
except Exception as e:
    print(f"[AppFactory] perf log setup failed: {e}")


# ---- Миграции: мягкий импорт ----
try:
    import migrations as _migr
    _HAS_MIGR = hasattr(_migr, "run_migrations")
except Exception:
    _HAS_MIGR = False
    _migr = None  # type: ignore


def run_migrations_for(app: Flask):
    with app.app_context():
        if _HAS_MIGR:
            _migr.run_migrations()  # type: ignore
        else:
            db.create_all()


# ---- Сессии без cookie ----
from flask.sessions import SessionInterface, SessionMixin


class _DisabledSession(dict, SessionMixin):
    pass


class NoCookieSessionInterface(SessionInterface):
    def open_session(self, app, request):
        return _DisabledSession()

    def save_session(self, app, session, response):
        return


# ---- Динамический загрузчик блюпринтов (для второстепенных модулей) ----
def _bp_or_none(module_path: str, errs: Dict[str, str]):
    try:
        mod = importlib.import_module(module_path)
        bp = getattr(mod, "bp", None)
        if bp is None:
            errs[module_path] = "module imported but has no `bp`"
        return bp
    except Exception:
        errs[module_path] = traceback.format_exc()
        return None


def create_app() -> Flask:
    # === Типы контента, чтобы браузеры не ругались на AVIF/WEBP ===
    import mimetypes
    mimetypes.add_type("image/avif", ".avif")
    mimetypes.add_type("image/webp", ".webp")

    app = Flask(__name__, static_folder="static", template_folder="templates")

    # ===== Конфиги =====
    app.config.setdefault("SECRET_KEY", os.getenv("SECRET_KEY", "dev-secret-change-me"))
    app.config.setdefault("TG_BOT_TOKEN", os.getenv("TG_BOT_TOKEN", "8134690532:AAETe0Hgj8rjrKBU4fpVhFcfgqqOjMMryhI"))
    app.config.setdefault("TG_BOT_USERNAME", os.getenv("TG_BOT_USERNAME", "flirtmod_bot"))
    app.config.setdefault("PREFERRED_URL_SCHEME", "https")

    try:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    except Exception:
        pass

    version_stamp = int(time.time())

    @app.context_processor
    def inject_static_version():
        return {"static_v": version_stamp}

    # ===== БД =====
    init_db_config(app)
    db.init_app(app)
    app.config.setdefault("DB_PATH", os.getenv("DB_PATH", "/var/www/pocketkingdom/app.db"))
    app.config.setdefault("ADMIN_PASS", os.getenv("ADMIN_PASS", "les"))

    # ===== Полностью отключаем cookie-сессии =====
    app.session_interface = NoCookieSessionInterface()

    # ===== Перф-лог по HTTP =====
    @app.before_request
    def _t0():
        request._t0 = time.perf_counter()

    @app.after_request
    def _http_log(resp):
        try:
            t0 = getattr(request, "_t0", None)
            if t0 is not None:
                dt_ms = (time.perf_counter() - t0) * 1000.0
                log({
                    "type": "http",
                    "path": request.path,
                    "method": request.method,
                    "status": resp.status_code,
                    "dur_ms": round(dt_ms, 2)
                })
        except Exception:
            pass
        return resp

    # ===== Фильтр монет =====
    @app.template_filter("coins")
    def coins_filter(v):
        try:
            n = float(v)
        except Exception:
            return v
        whole = int(round(n))
        return f"{whole:,}".replace(",", ".")

    # ===== Кеш-правила =====
    @app.after_request
    def _cache_headers(resp):
        p = request.path or ""
        if p.startswith("/static/tiles/") or p.startswith("/static/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            resp.headers.pop("Pragma", None)
            resp.headers.pop("Expires", None)
            return resp
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    # ===== Healthcheck =====
    @app.get("/healthz")
    def _health():
        return "ok", 200

    # ===== Список маршрутов =====
    @app.get("/_routes")
    def _routes():
        lines = []
        for r in app.url_map.iter_rules():
            methods = ",".join(sorted(r.methods - {"HEAD", "OPTIONS"}))
            lines.append(f"{methods:7} {r.rule} -> {r.endpoint}")
        return "<pre>" + "\n".join(sorted(lines)) + "</pre>", 200

    # ===== Поднимаем блюпринты =====
    _bp_errors: Dict[str, str] = {}
    public_bp    = _bp_or_none("routes_public",   _bp_errors)  # публичные страницы
    accounts_bp  = _bp_or_none("accounts.routes", _bp_errors)  # аккаунты/логин
    play_bp      = _bp_or_none("play.routes",     _bp_errors)  # мостик /play/**
    world_bp     = _bp_or_none("routes_world",    _bp_errors)  # страницы мира

    # ВАЖНО: НЕ импортируем никаких "world.api_resources" — добыча у нас в routes_world_resources.

    # Порядок: сначала accounts
    if public_bp and public_bp.name not in app.blueprints:
        app.register_blueprint(public_bp)
    if accounts_bp and accounts_bp.name not in app.blueprints:
        app.register_blueprint(accounts_bp)
    if play_bp and play_bp.name not in app.blueprints:
        app.register_blueprint(play_bp)
    if world_bp and world_bp.name not in app.blueprints:
        app.register_blueprint(world_bp)

    # Явные блюпринты (мир/добыча, инвентарь API и крафт API)
    if world_resources_bp and world_resources_bp.name not in app.blueprints:
        app.register_blueprint(world_resources_bp)
    else:
        app.logger.info("Blueprint 'world_resources' already registered, skipping")

    if world_combat_bp and world_combat_bp.name not in app.blueprints:
        app.register_blueprint(world_combat_bp)
    else:
        app.logger.info("Blueprint 'world_combat' already registered, skipping")

    if inv_bp and inv_bp.name not in app.blueprints:
        app.register_blueprint(inv_bp)
    else:
        app.logger.info(f"Blueprint '{getattr(inv_bp,'name','inventory_api')}' already registered, skipping")
    if craft_bp and craft_bp.name not in app.blueprints:
        app.register_blueprint(craft_bp)
    else:
        app.logger.info(f"Blueprint '{getattr(craft_bp,'name','craft_api')}' already registered, skipping")

    # ===== Защита входа на /world/*, /inv/*, /craft/* (нужен логин)
    @app.before_request
    def _gate_world_direct():
        p = (request.path or "")
        if p.startswith("/world") or p.startswith("/inv/") or p.startswith("/craft/"):
            # Подтянем текущего пользователя
            try:
                from accounts.routes import current_user as _acc_current_user
                if not getattr(g, "user", None):
                    g.user = _acc_current_user()
            except Exception:
                pass

            # user_id (для внутренних сервисов)
            if getattr(g, "user", None):
                uid = getattr(g.user, "id", None) or getattr(g.user, "uid", None)
                if uid is None and isinstance(g.user, dict):
                    uid = g.user.get("id") or g.user.get("uid")
                if uid is not None:
                    g.user_id = str(uid)
            if not getattr(g, "user_id", None):
                fp_src = f"{request.remote_addr}|{request.headers.get('User-Agent','')[:80]}"
                g.user_id = "anon:" + sha1(fp_src.encode("utf-8")).hexdigest()[:12]

            # редиректим неавторизованных с /world на логин
            if not getattr(g, "user", None):
                return redirect(url_for("accounts.landing"))

    # ===== Диагностика блюпринтов =====
    @app.get("/_bp_status")
    def _bp_status():
        loaded = []
        for name, bp in [
            ("routes_public",          public_bp),
            ("accounts.routes",        accounts_bp),
            ("play.routes",            play_bp),
            ("routes_world",           world_bp),
            ("routes_world_resources", world_resources_bp),
            ("routes_inventory",       inv_bp),
            ("routes_craft",           craft_bp),
        ]:
            loaded.append({
                "module": name,
                "loaded": bp is not None,
                "url_prefix": getattr(bp, "url_prefix", None) if bp else None,
                "err": _bp_errors.get(name)
            })
        return jsonify({"ok": True, "blueprints": loaded})

    # В лог — что не поднялось
    for name, err in _bp_errors.items():
        if err:
            print(f"[AppFactory] Blueprint import FAILED: {name}\n{err}\n")

    # ===== Миграции и инициализация =====
    run_migrations_for(app)
    
    # Инициализация крафт-системы
    try:
        with app.app_context():
            from craft_models import ensure_craft_models, seed_craft_recipes, seed_craft_items
            from accounts.models import ensure_accounts_models, seed_default_items
            
            ensure_accounts_models()
            seed_default_items()
            ensure_craft_models()
            seed_craft_recipes()
            seed_craft_items()
    except Exception as e:
        print(f"[AppFactory] craft models init failed: {e}")

    # ===== Главная =====
    def _first_existing(*endpoints: str) -> Optional[str]:
        for ep in endpoints:
            if ep in app.view_functions:
                return ep
        return None

    @app.get("/")
    def _home():
        target = app.config.get("HOME_ENDPOINT")
        if not target:
            target = _first_existing(
                "play.index",
                "accounts.landing",
                "world.page",
                "public.index",
            )
        if target:
            return redirect(url_for(target))

        html = [
            "<h1>Server is up</h1>",
            "<p>No home endpoint found. Available endpoints:</p>",
            "<ul>"
        ]
        for r in sorted(app.url_map.iter_rules(), key=lambda x: x.rule):
            if r.endpoint != "static":
                html.append(f"<li>{r.rule} → {r.endpoint}</li>")
        html.append("</ul>")
        return Response("\n".join(html), mimetype="text/html")

    return app
