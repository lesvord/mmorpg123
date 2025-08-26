import time
from functools import wraps
from typing import Optional, Tuple

from flask import current_app, request, jsonify, g
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

def _get_secret() -> str:
    # Используем AUTH_SECRET или ADMIN_PASS как запасной
    return current_app.config.get("AUTH_SECRET") or current_app.config.get("ADMIN_PASS") or "change-me"

def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_get_secret(), salt="auth-token-v1")

def issue_token(user_id: str, ttl_days: int = 30) -> str:
    s = _serializer()
    payload = {"uid": str(user_id), "iat": int(time.time()), "v":"1"}
    return s.dumps(payload)

def verify_token(token: str, max_age_days: int = 30) -> Optional[dict]:
    s = _serializer()
    try:
        return s.loads(token, max_age=max_age_days*24*3600)
    except (BadSignature, SignatureExpired):
        return None

def _extract_bearer() -> Optional[str]:
    h = request.headers.get("Authorization", "")
    if h.startswith("Bearer "):
        return h[7:].strip()
    # как запасной вариант – query-параметр ?token=...
    return request.args.get("token")

def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        tok = _extract_bearer()
        data = verify_token(tok) if tok else None
        if not data:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        g.auth = {"user_id": data.get("uid")}
        return fn(*args, **kwargs)
    return wrapper
