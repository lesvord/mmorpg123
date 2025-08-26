# app.py
import os
from app_factory import create_app

# === PERF настройки по умолчанию (можно переопределить через ENV) ===
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
os.environ.setdefault("PROJECT_ROOT", PROJECT_ROOT)

# Если PERF_LOG не задан, дублируем лог в <PROJECT_ROOT>/logs/perf.jsonl
# (это делает perf_monitor.enable(project_mirror=True))
os.environ.setdefault("PERF_SQL_SLOW_MS", "20")   # медленный SQL, мс
os.environ.setdefault("PERF_SVC_SLOW_MS", "40")   # медленная сервис-функция, мс
os.environ.setdefault("PERF_SQL_TEXT", "0")       # 1 — писать текст SQL (обрезается)

app = create_app()

# === Старт Telegram-бота в отдельном потоке (опционально) ===
try:
    from tg_bot_runner import start_bot_if_enabled
    start_bot_if_enabled(app)
except Exception as err:
    print(f"[TG BOT] start skipped: {err}")

# === Включаем perf_monitor ОДИН РАЗ, когда доступен app_context ===
try:
    import perf_monitor
    # При debug=True werkzeug запускает родителя и ребёнка.
    # Включаем только в рабочем процессе (child) или всегда в проде.
    should_enable = (not app.debug) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true")
    if should_enable:
        with app.app_context():
            # project_mirror=True добавит <PROJECT_ROOT>/logs/perf.jsonl
            perf_monitor.enable(project_mirror=True)
except Exception as err:
    print(f"[AppFactory] perf_monitor enable failed: {err}")

if __name__ == "__main__":
    # Локальный запуск: python app.py
    port = int(os.getenv("PORT", "5001"))
    debug = bool(int(os.getenv("DEBUG", "1")))
    app.run(host="0.0.0.0", port=port, debug=debug)
