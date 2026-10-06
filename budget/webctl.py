"""Проверка и запуск веб-приложения для агента (MCP `ensure_web_app`)."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

from budget.web.app import DEFAULT_PORT, HEALTH_TEXT

START_TIMEOUT_SEC = 15
# Процесс веб-приложения не должен завершаться вместе с MCP-сервером, который его запустил
DETACHED = (
    {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    if sys.platform == "win32" else {"start_new_session": True}
)


def is_running(port: int) -> bool:
    try:
        resp = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=1)
    except httpx.HTTPError:
        return False
    return resp.status_code == 200 and resp.text == HEALTH_TEXT


def port_busy(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_running(data_dir: Path, port: int = DEFAULT_PORT) -> dict:
    """Если веб-приложение не отвечает — запускает его отдельным процессом, переживающим MCP-сервер."""
    url = f"http://localhost:{port}"
    if is_running(port):
        return {"url": url, "started": False}
    if port_busy(port):
        raise RuntimeError(f"Порт {port} занят другим процессом (возможно, старой версией веб-приложения, "
                           f"запущенной вручную) — останови его, и приложение будет запускаться автоматически")
    data_dir.mkdir(parents=True, exist_ok=True)
    log = open(data_dir / "web.log", "a")
    proc = subprocess.Popen(
        [sys.executable, "-c", "from budget.web.app import main; main()"],
        env=os.environ | {"BUDGET_DATA_DIR": str(data_dir), "BUDGET_WEB_PORT": str(port)},
        stdout=log, stderr=log, stdin=subprocess.DEVNULL, **DETACHED,
    )
    deadline = time.monotonic() + START_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if is_running(port):
            return {"url": url, "started": True, "pid": proc.pid}
        time.sleep(0.3)
    raise RuntimeError(f"Веб-приложение не поднялось на порту {port} за {START_TIMEOUT_SEC} с; лог: {data_dir / 'web.log'}")
