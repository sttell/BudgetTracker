import json
import os
import tempfile
from pathlib import Path

from filelock import FileLock


class Storage:
    """JSON-файлы в data-директории: атомарная запись и общая блокировка для веба и MCP."""

    def __init__(self, root: Path):
        self.root = root
        self._lock = None

    def read(self, rel: str, default):
        path = self.root / rel
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def write(self, rel: str, data) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def list(self, rel_dir: str) -> list[str]:
        path = self.root / rel_dir
        return sorted(p.stem for p in path.glob("*.json")) if path.exists() else []

    def lock(self) -> FileLock:
        """Эксклюзивная межпроцессная блокировка на read-modify-write; повторный вход в том же потоке разрешён, потоки веб-сервера ждут друг друга."""
        if self._lock is None:
            self.root.mkdir(parents=True, exist_ok=True)
            self._lock = FileLock(self.root / ".lock")
        return self._lock
