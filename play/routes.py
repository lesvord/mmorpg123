from flask import Blueprint, redirect, url_for, g

bp = Blueprint("play", __name__, url_prefix="/play")

@bp.get("/")
def index():
    # нельзя в игру без авторизации
    if not getattr(g, "user", None):
        return redirect(url_for("accounts.landing"))
    # если мир доступен — туда; иначе на лендинг аккаунтов
    try:
        return redirect(url_for("world.page"))
    except Exception:
        return redirect(url_for("accounts.landing"))

# При желании можно добавить /play/world/* прокси-роуты,
# которые вызывают внутренние функции мира, подставляя g.user.
# Оставил минимальный индекс — уже закрывает внешний вход.
