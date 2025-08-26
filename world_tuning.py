# world_tuning.py
"""
Единая точка управления ускорением симуляции.
Поставь ACCEL=100.0 (или ENV WORLD_ACCEL=100) — и вся эволюция/погода/бакеты ускорятся.
Вернуть в прод — ACCEL=1.0 или переменная окружения WORLD_ACCEL=1.
"""

import os

def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except Exception:
        return default

# ГЛАВНЫЙ МНОЖИТЕЛЬ ВРЕМЕНИ:
# 1.0 — нормальный режим, 100.0 — ускорение в 100x
ACCEL: float = max(1.0, _float_env("WORLD_ACCEL", 1.0))

# --- ВРЕМЕННЫЕ ШКАЛЫ ---

# Длительность «бакета» для визуальных эфемерных эффектов (снег/болота) — было 1800 c
def bucket_seconds() -> float:
    base = 1800.0
    # делим базу на ACCEL, но не меньше 30с, чтобы не мигало слишком быстро
    return max(30.0, base / ACCEL)

# Длительность погодного слота — было 3600 c
def weather_slot_seconds() -> float:
    base = 3600.0
    return max(30.0, base / ACCEL)

# Минимальный период перманентной эволюции чанка — было 900 c
def evolve_min_period_seconds() -> float:
    base = 900.0
    return max(1.0, base / ACCEL)

# Кулдаун префетча колец — было 10 c
def prefetch_cooldown_seconds() -> float:
    base = 10.0
    return max(0.5, base / ACCEL)

# Во сколько раз быстрее накапливать экопоказатели wet/dry/heat/cold/forest_drive
def eco_time_accel() -> float:
    # линейно: если ACCEL=100, интегрируем как будто прошло в 100 раз больше часов
    return ACCEL

# Полураспады экологии — делим на ACCEL (быстрее реагирует)
def eco_half_life(hours: float) -> float:
    return max(0.1, hours / ACCEL)

# (Опционально) ослабить пороги мутаций при больших ускорениях
# Возвращает множитель для порогов (меньше 1.0 -> легче триггерятся)
def threshold_scale() -> float:
    # Нежно: при ACCEL>=50 делаем пороги ~в 2 раза легче
    if ACCEL >= 100.0:
        return 0.5
    elif ACCEL >= 50.0:
        return 0.66
    return 1.0
