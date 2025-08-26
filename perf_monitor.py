# perf_monitor.py
import os, time, threading, functools, traceback
from typing import Any, Dict, Optional, Iterable
from contextlib import contextmanager
from perf_logger import log, LOG, set_log_paths

# ------- настройки через ENV -------
SQL_SLOW_MS    = float(os.environ.get("PERF_SQL_SLOW_MS", 50))    # медленный SQL
SVC_SLOW_MS    = float(os.environ.get("PERF_SVC_SLOW_MS", 40))    # медленная сервис-функция
LOG_SQL_TEXT   = os.environ.get("PERF_SQL_TEXT", "0") == "1"      # писать текст SQL
# ВКЛЮЧИТЬ http-лог по сигналам Flask: PERF_FLASK_SIGNALS=1
HOOK_FLASKSIG  = os.environ.get("PERF_FLASK_SIGNALS", "0") == "1"

# ------- thread-local + гварды -------
_tls = threading.local()
_ENABLED = False  # гвард от повторного enable()

def _now() -> float:
    return time.perf_counter()

def _get_req_ctx() -> Dict[str, Any]:
    d = getattr(_tls, "ctx", None)
    if d is None:
        d = {
            "id": f"op-{int(time.time()*1000)}-{threading.get_ident()}",
            "sql_count": 0,
            "sql_time_ms": 0.0,
        }
        _tls.ctx = d
    return d

# -------------------- spans --------------------
@contextmanager
def span(kind: str, name: str, extra: Optional[Dict[str,Any]] = None):
    _get_req_ctx()  # ensure ctx exists
    t0 = _now()
    err = None
    try:
        yield
    except Exception as e:
        err = e
        raise
    finally:
        dt_ms = (_now() - t0) * 1000.0
        rec = {"type": kind, "name": name, "dur_ms": round(dt_ms, 2), "rid": _get_req_ctx()["id"]}
        if extra:
            rec.update(extra)
        if err:
            rec["error"] = str(err)
            rec["trace"] = traceback.format_exc(limit=3)
        if kind == "service" and dt_ms >= SVC_SLOW_MS:
            rec["slow"] = True
        log(rec)

def _wrap(fn, name: str):
    # не оборачиваем повторно
    if getattr(fn, "__perf_wrapped__", False):
        return fn

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        _get_req_ctx()
        with span("service", name):
            return fn(*args, **kwargs)
    wrapper.__perf_wrapped__ = True
    return wrapper

def _wrap_named(obj, func_name: str):
    if hasattr(obj, func_name):
        setattr(obj, func_name, _wrap(getattr(obj, func_name), func_name))

# -------------------- services_world hot funcs --------------------
def _wrap_services_world():
    """
    Профилируем «горячие» функции сервиса.
    Оставлено на случай, если модуль отсутствует — тогда тихо выходим.
    """
    try:
        import services_world as sw  # type: ignore
    except Exception:
        return
    for fname in [
        "get_world_state", "get_patch_view",
        "set_destination", "stop_hero", "set_speed",
        "build_here", "rest_here", "wake_up", "camp_start", "camp_leave",
        "_advance", "_patch",
    ]:
        _wrap_named(sw, fname)

# -------------------- SQLAlchemy hooks (Engine-wide) --------------------
def _install_sqlalchemy_events():
    """
    Подписываемся глобально на Engine-класс — не требует app_context.
    Работает для всех будущих подключений SQLAlchemy в процессе.
    """
    try:
        from sqlalchemy import event  # type: ignore
        from sqlalchemy.engine import Engine  # type: ignore
    except Exception:
        return

    @event.listens_for(Engine, "before_cursor_execute", named=True)
    def _before_cursor_execute(**kw):
        context = kw.get("context")
        if context is not None:
            context._query_start_time = _now()

    @event.listens_for(Engine, "after_cursor_execute", named=True)
    def _after_cursor_execute(**kw):
        context  = kw.get("context")
        cursor   = kw.get("cursor")
        statement = kw.get("statement")
        if context is None:
            return
        start = getattr(context, "_query_start_time", None)
        if start is None:
            return
        dt_ms = (_now() - start) * 1000.0
        ctx = _get_req_ctx()
        ctx["sql_count"] += 1
        ctx["sql_time_ms"] += dt_ms
        if dt_ms >= SQL_SLOW_MS:
            rec = {
                "type": "sql", "slow": True, "dur_ms": round(dt_ms, 2),
                "rid": ctx["id"],
                "rowcount": getattr(cursor, "rowcount", None),
            }
            if LOG_SQL_TEXT and statement:
                sql_txt = str(statement).replace("\n", " ")
                if len(sql_txt) > 800:
                    sql_txt = sql_txt[:800] + "…"
                rec["sql"] = sql_txt
            log(rec)

# -------------------- Flask signals (optional) --------------------
def _attempt_flask_request_hooks():
    """
    Через сигналы Flask. Выключено по умолчанию (HOOK_FLASKSIG),
    чтобы не дублировать с ручным after_request в app_factory.py.
    Включение: PERF_FLASK_SIGNALS=1
    """
    if not HOOK_FLASKSIG:
        return
    try:
        from flask import request_started, request_finished
    except Exception:
        return

    @request_started.connect_via(None)
    def _on_started(sender, **extra):
        # Новый RID для каждого HTTP-запроса + фиксация метода/пути
        env = extra.get("environ") if extra else None
        method = env.get("REQUEST_METHOD") if env else None
        # SCRIPT_NAME учитывает возможный префикс приложения
        script_name = (env.get("SCRIPT_NAME") or "") if env else ""
        path_info   = (env.get("PATH_INFO")   or "") if env else ""
        path = f"{script_name}{path_info}" or None
        _tls.ctx = {
            "id": f"http-{int(time.time()*1000)}-{threading.get_ident()}",
            "sql_count": 0,
            "sql_time_ms": 0.0,
            "_t0": _now(),
            "_method": method,
            "_path": path,
        }

    @request_finished.connect_via(None)
    def _on_finished(sender, response, **extra):
        ctx = getattr(_tls, "ctx", None)
        if not ctx:
            return
        dt_ms = (_now() - ctx.get("_t0", _now())) * 1000.0
        rec = {
            "type": "http",
            "dur_ms": round(dt_ms, 2),
            "rid": ctx["id"],
            "sql_count": ctx.get("sql_count", 0),
            "sql_time_ms": round(ctx.get("sql_time_ms", 0.0), 2),
            "status": getattr(response, "status_code", None),
            "size": (getattr(response, "calculate_content_length", lambda: None)() or
                     getattr(response, "content_length", None)),
        }
        # Добавим метод/путь, если удалось поймать на старте
        if ctx.get("_method"):
            rec["method"] = ctx["_method"]
        if ctx.get("_path"):
            rec["path"] = ctx["_path"]
        log(rec)

# -------------------- public API --------------------
def enable(log_path: Optional[str] = None,
           mirror_path: Optional[str] = None,
           project_mirror: bool = False,
           extra_paths: Optional[Iterable[str]] = None):
    """
    Включить профилинг.
    - log_path: основной путь (по умолчанию PERF_LOG или /tmp/perf.jsonl)
    - mirror_path: явный путь для дубля
    - project_mirror: если True, добавить <PROJECT_ROOT>/logs/perf.jsonl
    - extra_paths: список дополнительных путей

    Параметры можно задавать только через ENV:
      PERF_LOG, PERF_LOG2, PERF_LOG_PROJECT=1, PROJECT_ROOT
    """
    global _ENABLED
    if _ENABLED:
        return
    _ENABLED = True

    paths = []
    if log_path:
        paths.append(log_path)
    else:
        paths.append(os.environ.get("PERF_LOG", "/tmp/perf.jsonl"))
    if mirror_path:
        paths.append(mirror_path)
    if project_mirror or os.environ.get("PERF_LOG_PROJECT", "0") == "1":
        proj = os.environ.get("PROJECT_ROOT")
        if not proj:
            import sys, os as _os
            proj = (sys.path[0] if sys.path and _os.path.isdir(sys.path[0]) else _os.getcwd())
        paths.append(os.path.join(proj, "logs", "perf.jsonl"))
    if os.environ.get("PERF_LOG2"):
        paths.append(os.environ["PERF_LOG2"])
    if extra_paths:
        paths.extend(extra_paths)

    # применить (убираем дубликаты внутри set_log_paths)
    set_log_paths(paths)

    # остальная инициализация
    _wrap_services_world()
    _install_sqlalchemy_events()
    _attempt_flask_request_hooks()
    log({"type": "perfmon", "event": "enabled", "pid": os.getpid(), "paths": paths})
