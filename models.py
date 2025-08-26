# models.py
import os
import sqlite3
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.engine import Engine

# Можно переопределить через переменную окружения:
#   DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname
DEFAULT_DB_URI = os.getenv("DATABASE_URL", "sqlite:///app.db")

db = SQLAlchemy(session_options={"autoflush": False, "autocommit": False})


def init_db_config(app):
    """Применяет базовые настройки БД, если они ещё не заданы."""
    app.config.setdefault("SQLALCHEMY_DATABASE_URI", DEFAULT_DB_URI)

    # Базовые опции движка
    opts = app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {"pool_pre_ping": True})

    # Для sqlite — мягкие настройки подключения + таймауты
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if uri.startswith("sqlite:"):
        connect_args = opts.setdefault("connect_args", {})
        connect_args.setdefault("timeout", 5)               # ожидание блокировок
        connect_args.setdefault("check_same_thread", False) # если используем фоновые треды

    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)
    # Для больших ответов JSON без артефактов
    app.config.setdefault("JSON_AS_ASCII", False)
    app.config.setdefault("JSON_SORT_KEYS", False)

    # Глобальные PRAGMA для sqlite (WAL + более дешёвый fsync и т.д.)
    @event.listens_for(Engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _):
        if isinstance(dbapi_conn, sqlite3.Connection):
            cur = dbapi_conn.cursor()
            try:
                # быстрые и стабильные настройки для локальной sqlite
                cur.execute("PRAGMA journal_mode=WAL;")
                cur.execute("PRAGMA synchronous=NORMAL;")
                cur.execute("PRAGMA temp_store=MEMORY;")
                cur.execute("PRAGMA cache_size=-20000;")        # ~20МБ page cache
                cur.execute("PRAGMA wal_autocheckpoint=4000;")  # реже чекпоинты
                cur.execute("PRAGMA foreign_keys=ON;")
            finally:
                cur.close()


def bind_db(app):
    """Удобный хелпер: применяет конфиг и привязывает db к приложению."""
    init_db_config(app)
    db.init_app(app)
    return db
