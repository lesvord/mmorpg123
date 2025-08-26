import os
from perf_monitor import enable

# лог прямо в папке проекта
log_main = os.path.join(os.getcwd(), "logs", "perf.jsonl")
os.makedirs(os.path.dirname(log_main), exist_ok=True)

# включаем профилинг и указываем путь
enable(log_path=log_main, project_mirror=False)
