import os, json, time, threading
from typing import Any, Dict, Optional, IO, Iterable, List

def _ensure_dir_for(path: str):
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)

class JsonlLogger:
    def __init__(self, path: str, rotate_mb: int = 100, backups: int = 5):
        self.path = path
        self.rotate_bytes = int(rotate_mb * 1024 * 1024)
        self.backups = int(backups)
        self._lock = threading.RLock()
        self._fh: Optional[IO[str]] = None
        _ensure_dir_for(self.path)

    def _open(self):
        if self._fh is None:
            self._fh = open(self.path, "a", buffering=1, encoding="utf-8")

    def _size(self) -> int:
        try: return os.path.getsize(self.path)
        except Exception: return 0

    def _rotate(self):
        if self._fh:
            try: self._fh.close()
            except Exception: pass
            self._fh = None
        for i in range(self.backups-1, 0, -1):
            src = f"{self.path}.{i}"
            dst = f"{self.path}.{i+1}"
            if os.path.exists(src):
                try: os.replace(src, dst)
                except Exception: pass
        try:
            os.replace(self.path, f"{self.path}.1")
        except Exception:
            pass

    def log(self, rec: Dict[str, Any]):
        rec.setdefault("ts", time.time())
        line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._open()
            try:
                self._fh.write(line + "\n")
            except Exception:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = None
                self._open()
                self._fh.write(line + "\n")
            if self._size() >= self.rotate_bytes:
                self._rotate()
                self._open()

class TeeLogger:
    """Пишет в несколько логгеров сразу (дублирование)."""
    def __init__(self, loggers: Iterable[JsonlLogger]):
        self._loggers = list(loggers)

    def log(self, rec: Dict[str, Any]):
        for lg in self._loggers:
            try:
                lg.log(rec)
            except Exception:
                pass

# ---------- глобальная инициализация (с поддержкой дубляжа) ----------
def _guess_project_root() -> str:
    # приоритетно env, затем sys.path[0], затем cwd
    root = os.environ.get("PROJECT_ROOT")
    if root:
        return root
    try:
        import sys
        if sys.path and os.path.isdir(sys.path[0]):
            return sys.path[0]
    except Exception:
        pass
    return os.getcwd()

def _build_logger_from_env():
    primary_path = os.environ.get("PERF_LOG", "/tmp/perf.jsonl")
    mirror_env   = os.environ.get("PERF_LOG2", "")  # явный путь для зеркала
    project_dup  = os.environ.get("PERF_LOG_PROJECT", "0") == "1"

    loggers: List[JsonlLogger] = [JsonlLogger(primary_path)]

    if mirror_env:
        loggers.append(JsonlLogger(mirror_env))
    elif project_dup:
        proj = _guess_project_root()
        mirror_path = os.path.join(proj, "logs", "perf.jsonl")
        loggers.append(JsonlLogger(mirror_path))

    if len(loggers) == 1:
        return loggers[0]
    return TeeLogger(loggers)

# Глобальный инстанс; можно переинициализировать через set_log_paths(...)
LOG = _build_logger_from_env()

def log(rec: Dict[str, Any]):  # внешний шорткат
    LOG.log(rec)

# Позволяет программно задать один или несколько путей (например, из perf_monitor.enable)
def set_log_paths(paths: Iterable[str]):
    global LOG
    paths = list(dict.fromkeys(paths))  # убрать дубликаты, сохраняя порядок
    if not paths:
        return
    LOG = TeeLogger([JsonlLogger(p) for p in paths]) if len(paths) > 1 else JsonlLogger(paths[0])
