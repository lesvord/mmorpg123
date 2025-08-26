from __future__ import annotations
import hmac
import time
import hashlib
import json
import urllib.parse
from typing import Optional, Dict, List

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, g, current_app, jsonify
)
from sqlalchemy.exc import IntegrityError

from models import db
# импортируем всё, что нужно из внутренних моделей/утилит
from .models import (
    User, PlayerProfile,
    ensure_accounts_models, seed_default_items,
    equipped_by_slot, list_inventory, inventory_totals
)
# JWT-авторизация (новая кука pk_auth) — используем как фолбэк
from .auth import current_user as jwt_current_user, set_auth_cookie as set_auth_cookie_jwt

bp = Blueprint("accounts", __name__, url_prefix="/accounts")

# ---------- простая auth-cookie (подписанный токен) ----------
COOKIE_NAME = "acc"
COOKIE_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 дней


def _sign(s: str) -> str:
    secret = (current_app.config.get("SECRET_KEY") or "dev-secret").encode("utf-8")
    return hmac.new(secret, s.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(user_id: int, ttl: int = COOKIE_TTL_SECONDS) -> str:
    exp = int(time.time()) + int(ttl)
    body = f"{user_id}.{exp}"
    sig = _sign(body)
    return f"{body}.{sig}"


def parse_token(tok: str) -> Optional[int]:
    try:
        uid_s, exp_s, sig = tok.split(".", 2)
        if _sign(f"{uid_s}.{exp_s}") != sig:
            return None
        if time.time() > float(exp_s):
            return None
        return int(uid_s)
    except Exception:
        return None


def set_auth_cookie(resp, user_id: int):
    """
    Ставим обе куки, чтобы фронт и старые/новые ручки видели авторизацию.
    """
    # старая кука "acc"
    tok = make_token(user_id)
    resp.set_cookie(
        COOKIE_NAME, tok,
        max_age=COOKIE_TTL_SECONDS,
        httponly=True, samesite="Lax", secure=False  # в проде secure=True
    )
    # новая кука "pk_auth" (JWT)
    try:
        set_auth_cookie_jwt(resp, user_id)
    except Exception:
        pass


def clear_auth_cookie(resp):
    resp.delete_cookie(COOKIE_NAME, samesite="Lax")
    # чистим и JWT
    try:
        from .auth import clear_auth_cookie as clear_jwt_cookie
        clear_jwt_cookie(resp)
    except Exception:
        resp.set_cookie("pk_auth", "", expires=0, path="/")


def current_user() -> Optional[User]:
    """
    1) Пытаемся прочитать старую куку acc.
    2) Фолбэк — JWT pk_auth (accounts.auth).
    """
    # путь 1: acc
    tok = request.cookies.get(COOKIE_NAME)
    if tok:
        uid = parse_token(tok)
        if uid:
            try:
                u = User.query.get(uid)
                if u:
                    return u
            except Exception:
                pass

    # путь 2: JWT pk_auth
    try:
        u = jwt_current_user()
        if u:
            return u
    except Exception:
        pass

    return None


# Делаем пользователя доступным везде через g.user
@bp.before_app_request
def _load_user():
    g.user = current_user()


# ---------- страницы ----------
@bp.get("/")
@bp.get("/landing")
def landing():
    return render_template("accounts/landing.html")


@bp.get("/login")
def login_get():
    return render_template("accounts/login.html")


@bp.post("/login")
def login_post():
    email = (request.form.get("email") or "").strip().lower()
    pw = request.form.get("password") or ""
    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(pw):
        flash("Неверный email или пароль")
        return redirect(url_for("accounts.login_get"))
    user.touch_login()
    db.session.add(user)
    db.session.commit()
    resp = redirect(url_for("play.index"))
    set_auth_cookie(resp, user.id)
    return resp


@bp.get("/register")
def register_get():
    return render_template("accounts/register.html")


@bp.post("/register")
def register_post():
    email = (request.form.get("email") or "").strip().lower()
    username = (request.form.get("username") or "").strip()
    pw = request.form.get("password") or ""

    if not email or not username or not pw:
        flash("Заполните все поля")
        return redirect(url_for("accounts.register_get"))

    if User.query.filter((User.email == email) | (User.username == username)).first():
        flash("Такой email или ник уже занят")
        return redirect(url_for("accounts.register_get"))

    u = User(email=email, username=username)
    u.set_password(pw)
    db.session.add(u)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("Такой email или ник уже занят")
        return redirect(url_for("accounts.register_get"))

    resp = redirect(url_for("play.index"))
    set_auth_cookie(resp, u.id)
    return resp


@bp.get("/logout")
def logout():
    resp = redirect(url_for("accounts.landing"))
    clear_auth_cookie(resp)
    return resp


# ---------- Профиль (страница) ----------
@bp.get("/profile")
def profile_page():
    if not g.get("user"):
        return redirect(url_for("accounts.login_get"))

    u = g.user
    # гарантируем наличие профиля (на старых БД запись могла не создаться)
    prof = getattr(u, "profile", None)
    if prof is None:
        prof = PlayerProfile(user_id=u.id)
        db.session.add(prof)
        db.session.commit()

    eq = equipped_by_slot(u.id)
    inv_rows = list_inventory(u.id)
    inv_tot = inventory_totals(u.id)

    return render_template(
        "accounts/profile.html",
        user=u,
        profile=prof,
        equipped=eq,
        inventory=inv_rows,
        inv_totals=inv_tot
    )


# ---------- API для фронта ----------
@bp.get("/whoami")
def whoami():
    u = g.get("user") or current_user()
    if not u:
        return jsonify({"ok": True, "user": None})
    return jsonify({
        "ok": True,
        "user": {
            "id": u.id, "email": u.email, "username": u.username,
            "tg_id": u.tg_id, "tg_username": u.tg_username
        }
    })


@bp.get("/profile_api")
def profile_api():
    """
    Лёгкий JSON для оверлея: профиль и базовые статы (включая stamina_max и gold),
    плюс суммарный вес инвентаря и грузоподъёмность.
    """
    u = g.get("user") or current_user()
    if not u:
        return jsonify({"ok": False, "error": "auth_required"}), 401

    prof = getattr(u, "profile", None)
    if prof is None:
        prof = PlayerProfile(user_id=u.id)
        db.session.add(prof)
        db.session.commit()

    inv_tot = inventory_totals(u.id)

    return jsonify({
        "ok": True,
        "user": {"id": u.id, "username": u.username, "email": u.email},
        "profile": prof.as_dict(),
        "inventory": {
            "weight_kg": inv_tot["weight_kg"],
            "capacity_kg": inv_tot["capacity_kg"],
            "load_pct": inv_tot["load_pct"],
        }
    })


# ---------- Telegram Login Widget (старый способ) ----------
def _verify_tg_login(params: Dict[str, str]) -> Optional[Dict[str, str]]:
    """
    Проверка данных от Telegram Login Widget.
    Поля в query и 'hash'. Секрет = sha256(bot_token).
    """
    bot_token = (current_app.config.get("TG_BOT_TOKEN") or "").strip()
    if not bot_token:
        return None

    data = dict(params)
    their_hash = data.pop("hash", None)
    if not their_hash:
        return None

    # data_check_string
    pairs = [f"{k}={data[k]}" for k in sorted(data.keys())]
    dcs = "\n".join(pairs)

    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    h = hmac.new(secret_key, dcs.encode("utf-8"), hashlib.sha256).hexdigest()

    if h != their_hash:
        return None

    # проверка давности (по желанию)
    try:
        auth_date = int(data.get("auth_date", "0"))
        if auth_date and (time.time() - auth_date) > 600:
            return None
    except Exception:
        pass

    return data


@bp.get("/tg/start")
def tg_start():
    """
    Стартовая страница:
      - Если открыто внутри Telegram WebApp — автоматически постим initData на /accounts/tg/webapp_finish.
      - Иначе показываем виджет и deep link.
    """
    return render_template(
        "accounts/tg_start.html",
        bot_username=(current_app.config.get("TG_BOT_USERNAME") or ""),
        deep_link=f"https://t.me/{current_app.config.get('TG_BOT_USERNAME','')}" + "?startapp=play"
    )


@bp.get("/tg/finish")
def tg_finish():
    """Финиш для Login Widget (не для WebApp)."""
    data = _verify_tg_login(request.args.to_dict())
    if not data:
        flash("Telegram не настроен или подпись невалидна")
        return redirect(url_for("accounts.landing"))

    tg_id = str(data.get("id") or data.get("user_id") or "")
    if not tg_id:
        flash("Нет tg id")
        return redirect(url_for("accounts.landing"))

    u = User.query.filter_by(tg_id=tg_id).first()
    if not u:
        username = (data.get("username") or f"tg{tg_id}")[:40]
        email = f"tg_{tg_id}@local"
        u = User(
            email=email,
            username=username,
            tg_id=tg_id,
            tg_username=data.get("username")
        )
        db.session.add(u)
        db.session.commit()
    else:
        u.tg_username = data.get("username") or u.tg_username
        u.touch_login()
        db.session.add(u)
        db.session.commit()

    resp = redirect(url_for("play.index"))
    set_auth_cookie(resp, u.id)
    return resp


# ---------- Telegram WebApp (автовход внутри Telegram) ----------
def _verify_webapp_initdata(init_data: str) -> Optional[Dict[str, str]]:
    """
    Проверка initData из Telegram WebApp.
    Алгоритм (официальный):
      - secret_key = HMAC_SHA256(key="WebAppData", data=bot_token)
      - data_check_string = lines sorted "key=value" (все поля кроме 'hash')
      - h = HMAC_SHA256(secret_key, data_check_string)
      - compare hex(h) == hash (из initData)
    """
    bot_token = (current_app.config.get("TG_BOT_TOKEN") or "").strip()
    if not bot_token or not init_data:
        return None

    # разбор init_data в dict
    pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
    data = {k: v for (k, v) in pairs}
    their_hash = data.pop("hash", None)
    if not their_hash:
        return None

    # Telegram WebApp — секрет формируется через HMAC("WebAppData", bot_token)
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

    # data_check_string
    dcs_parts = []
    for k in sorted(data.keys()):
        dcs_parts.append(f"{k}={data[k]}")
    dcs = "\n".join(dcs_parts)

    h = hmac.new(secret_key, dcs.encode("utf-8"), hashlib.sha256).hexdigest()
    if h != their_hash:
        return None

    # (опционально) проверка давности через query_id/user/auth_date — по желанию
    return data


@bp.post("/tg/webapp_finish")
def tg_webapp_finish():
    """
    Принимает initData (form/json/header), валидирует, логинит/создаёт пользователя.
    Возвращает JSON {ok:true, redirect:"..."} либо делает redirect, если не JSON.
    """
    # initData может приходить:
    # - body form: init_data=...
    # - body json: {"init_data": "..."}
    # - header: X-Telegram-Init-Data
    raw = (
        (request.form.get("init_data") or "").strip()
        or (request.json.get("init_data").strip() if request.is_json and isinstance(request.json, dict) else "")
        or (request.headers.get("X-Telegram-Init-Data") or "").strip()
    )

    data = _verify_webapp_initdata(raw)
    if not data:
        # единый ответ для фронта, который показал "bad_or_missing_initdata"
        return jsonify({"ok": False, "message": "bad_or_missing_initdata"}), 400

    # В initData есть поле 'user' — JSON-строка
    try:
        user_obj = json.loads(data.get("user", "{}"))
    except Exception:
        user_obj = {}

    tg_id = str(user_obj.get("id") or "")
    tg_username = user_obj.get("username") or ""
    if not tg_id:
        return jsonify({"ok": False, "message": "no_tg_id_in_webapp_user"}), 400

    u = User.query.filter_by(tg_id=tg_id).first()
    if not u:
        username = (tg_username or f"tg{tg_id}")[:40]
        email = f"tg_{tg_id}@local"
        u = User(email=email, username=username, tg_id=tg_id, tg_username=tg_username)
        db.session.add(u)
        db.session.commit()
    else:
        u.tg_username = tg_username or u.tg_username
        u.touch_login()
        db.session.add(u)
        db.session.commit()

    # Если пришёл fetch из JS — вернём JSON. Иначе — редирект.
    target = url_for("play.index")
    if "application/json" in (request.headers.get("Accept") or ""):
        resp = jsonify({"ok": True, "redirect": target})
    else:
        resp = redirect(target)
    set_auth_cookie(resp, u.id)
    return resp


# ---------- первичная инициализация таблиц/сидов ----------
@bp.record_once
def _init_accounts(setup_state):
    app = setup_state.app
    with app.app_context():
        ensure_accounts_models()
        try:
            seed_default_items()
        except Exception as e:
            app.logger.warning("seed_default_items failed: %s", e)


@bp.record_once
def _on_load(setup_state):
    app = setup_state.app
    with app.app_context():
        ensure_accounts_models()
