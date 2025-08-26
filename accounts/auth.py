# accounts/auth.py
import os, time, hmac, json, base64, hashlib
from functools import wraps
from typing import Optional, Tuple
from flask import request, redirect, url_for, current_app, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from models import db
from .models import User

AUTH_SECRET = os.getenv("AUTH_SECRET", "dev-secret-change-me").encode("utf-8")
COOKIE_NAME = "pk_auth"
COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "1") == "1"

# --- мини-JWT (HS256) без зависимостей ---
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

def _b64url_json(obj) -> str:
    return _b64url(json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))

def _sign(data: bytes) -> str:
    sig = hmac.new(AUTH_SECRET, data, hashlib.sha256).digest()
    return _b64url(sig)

def issue_token(user_id: int, ttl_sec: int = 30 * 24 * 3600) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"uid": user_id, "iat": now, "exp": now + ttl_sec}
    h = _b64url_json(header)
    p = _b64url_json(payload)
    s = _sign(f"{h}.{p}".encode("ascii"))
    return f"{h}.{p}.{s}"

def verify_token(token: str) -> Optional[dict]:
    try:
        h, p, s = token.split(".")
        expected = _sign(f"{h}.{p}".encode("ascii"))
        if not hmac.compare_digest(expected, s):
            return None
        obj = json.loads(base64.urlsafe_b64decode(p + "==").decode("utf-8"))
        if int(time.time()) >= int(obj.get("exp", 0)):
            return None
        return obj
    except Exception:
        return None

def current_user() -> Optional[User]:
    tok = request.cookies.get(COOKIE_NAME)
    if not tok:
        return None
    data = verify_token(tok)
    if not data:
        return None
    return User.query.get(int(data["uid"]))

def set_auth_cookie(resp, user_id: int):
    tok = issue_token(user_id)
    resp.set_cookie(
        COOKIE_NAME, tok,
        httponly=True, secure=COOKIE_SECURE, samesite="Lax",
        max_age=30*24*3600, path="/"
    )

def clear_auth_cookie(resp):
    resp.set_cookie(COOKIE_NAME, "", expires=0, path="/")

def login_required(fn):
    @wraps(fn)
    def _w(*a, **kw):
        u = current_user()
        if not u:
            if request.accept_mimetypes.accept_json and request.method != "GET":
                return {"ok": False, "error": "auth_required"}, 401
            return redirect(url_for("accounts.landing"))
        return fn(*a, **kw)
    return _w

# --- пароли ---
def hash_password(pw: str) -> str:
    return generate_password_hash(pw)

def verify_password(hashv: str, pw: str) -> bool:
    return check_password_hash(hashv or "", pw or "")

# --- Telegram Login verification ---
def verify_telegram_payload(data: dict) -> Optional[Tuple[str, dict]]:
    """
    Возвращает (tg_id, data) если всё ок.
    Ожидаем поля Telegram Login Widget:
      id, first_name, last_name?, username?, photo_url?, auth_date, hash
    """
    bot_token = os.getenv("TG_BOT_TOKEN", "")
    if not bot_token:
        return None
    check_hash = data.get("hash")
    if not check_hash:
        return None

    secret = hashlib.sha256(bot_token.encode("utf-8")).digest()
    pairs = []
    for k in sorted(data.keys()):
        if k == "hash":
            continue
        pairs.append(f"{k}={data[k]}")
    check_string = "\n".join(pairs).encode("utf-8")
    calc_hash = hmac.new(secret, check_string, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, check_hash):
        return None

    # свежесть (по желанию можно ужесточить)
    try:
        auth_date = int(data.get("auth_date", "0"))
        if time.time() - auth_date > 24*3600:
            return None
    except Exception:
        return None

    return str(data["id"]), data
