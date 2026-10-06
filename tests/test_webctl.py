import os
import signal
import socket

from budget.webctl import ensure_running, is_running


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_ensure_running_starts_once(tmp_path):
    port = free_port()
    assert not is_running(port)
    first = ensure_running(tmp_path, port)
    try:
        assert first["started"] and is_running(port)
        assert ensure_running(tmp_path, port) == {"url": f"http://localhost:{port}", "started": False}
    finally:
        os.kill(first["pid"], signal.SIGTERM)


def test_busy_port_fails_fast(tmp_path):
    import pytest

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        with pytest.raises(RuntimeError, match="занят"):
            ensure_running(tmp_path, s.getsockname()[1])
