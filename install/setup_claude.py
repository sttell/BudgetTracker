"""Подключает BudgetTracker к Claude: MCP-сервер в Claude Desktop и Claude Code, скилл для обоих.

Запускается из install.sh / install.ps1; можно и вручную:
    uv run python install/setup_claude.py [--uninstall]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVER_NAME = "budget"
SKILL_NAME = "budget-tracker"
SKILL_SRC = REPO / "skills" / SKILL_NAME
SKILL_ZIP = REPO / "dist" / f"{SKILL_NAME}-skill.zip"


def desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Claude" / "claude_desktop_config.json"


def find_uv() -> str:
    uv = shutil.which("uv") or next(
        (str(p) for p in [Path.home() / ".local" / "bin" / "uv", Path.home() / ".cargo" / "bin" / "uv"] if p.exists()),
        None,
    )
    if uv is None:
        sys.exit("Не найден uv. Установите его: https://docs.astral.sh/uv/getting-started/installation/")
    return str(Path(uv).resolve())


def mcp_args(uv: str) -> list[str]:
    return [uv, "run", "--directory", str(REPO), "budget-mcp"]


def update_desktop(uv: str | None) -> None:
    path = desktop_config_path()
    if not path.parent.exists():
        print(f"- Claude Desktop не найден ({path.parent}) — пропускаю")
        return
    config = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(path, backup)
    servers = config.setdefault("mcpServers", {})
    if uv:
        command, *args = mcp_args(uv)
        servers[SERVER_NAME] = {"command": command, "args": args}
    else:
        servers.pop(SERVER_NAME, None)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"- Claude Desktop: MCP-сервер «{SERVER_NAME}» {'добавлен' if uv else 'удалён'} ({path})")


def update_claude_code(uv: str | None) -> None:
    claude = shutil.which("claude")
    skill_dir = Path.home() / ".claude" / "skills" / SKILL_NAME
    if claude is None:
        print("- Claude Code (CLI) не найден — пропускаю")
        return
    subprocess.run([claude, "mcp", "remove", "--scope", "user", SERVER_NAME], capture_output=True)
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    if uv:
        subprocess.run([claude, "mcp", "add", "--scope", "user", SERVER_NAME, "--", *mcp_args(uv)], check=True,
                       capture_output=True)
        shutil.copytree(SKILL_SRC, skill_dir)
    print(f"- Claude Code: MCP-сервер и скилл {'установлены' if uv else 'удалены'} ({skill_dir})")


def build_skill_zip() -> None:
    SKILL_ZIP.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(SKILL_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(SKILL_SRC.rglob("*")):
            if file.is_file():
                zf.write(file, Path(SKILL_NAME) / file.relative_to(SKILL_SRC))
    print(f"- Скилл для Claude Desktop собран: {SKILL_ZIP}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uninstall", action="store_true", help="убрать MCP-сервер и скилл из Claude")
    parser.add_argument("--uv", help="путь к uv (по умолчанию ищется автоматически)")
    args = parser.parse_args()

    uv = None if args.uninstall else (args.uv or find_uv())
    update_desktop(uv)
    update_claude_code(uv)
    if args.uninstall:
        print("\nГотово. Скилл в Claude Desktop удалите вручную: Settings → Capabilities → Skills.")
        print(f"Данные остались в {REPO / 'data'} — удалите папку, если они не нужны.")
        return
    build_skill_zip()
    print(f"""
Готово. Осталось два шага руками:
  1. Полностью перезапустите Claude Desktop (выйти из приложения и открыть снова).
  2. Загрузите скилл: Settings → Capabilities → Skills → Upload → {SKILL_ZIP}

Веб-интерфейс: агент поднимает его сам, вручную — `uv run --directory "{REPO}" budget-web`,
затем http://localhost:5050 → Настройки: валюты, таргет на месяц, фиксированные траты.""")


if __name__ == "__main__":
    main()
