# BudgetTracker

Локальный трекер личного бюджета: траты вносятся через AI-агента по MCP (диктовка, скриншоты банковских приложений) или руками в веб-интерфейсе. Данные — JSON-файлы в `data/` (не в git). Дизайн: [docs/DESIGN.md](docs/DESIGN.md).

## Установка

Одной командой — macOS / Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/sttell/BudgetTracker/main/install/install.sh | bash
```

Windows (PowerShell): `irm https://raw.githubusercontent.com/sttell/BudgetTracker/main/install/install.ps1 | iex`

Подробно — что ставится, первая настройка, обновление и удаление: [install/README.md](install/README.md).

Для разработки: `uv sync`.

## Веб-интерфейс

```bash
uv run budget-web
```

Открыть http://localhost:5050.

## MCP-сервер

- **Claude Code** в этой директории подхватит сервер `budget` из `.mcp.json`.
- **Claude Desktop** (чат): добавить в `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "budget": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--directory", "/path/to/BudgetTracker", "budget-mcp"]
    }
  }
}
```

Claude Desktop не видит PATH оболочки, поэтому путь к `uv` — абсолютный.

## Скилл для Claude Desktop

`skills/budget-tracker/SKILL.md` — когда и как агенту работать с бюджетом. Собрать архив и загрузить его в Claude Desktop: Settings → Capabilities → Skills → Upload.

```bash
cd skills && zip -r ../dist/budget-tracker-skill.zip budget-tracker
```

Путь к данным можно переопределить переменной `BUDGET_DATA_DIR`.

## Тесты

```bash
uv run pytest
```
