#!/usr/bin/env bash
# Установка BudgetTracker на macOS / Linux:
#   curl -fsSL https://raw.githubusercontent.com/sttell/BudgetTracker/main/install/install.sh | bash
# Повторный запуск обновляет установку. Переменные окружения:
#   BUDGET_TRACKER_DIR  — куда установить (по умолчанию ~/BudgetTracker)
#   BUDGET_TRACKER_REPO — git-репозиторий (по умолчанию https://github.com/sttell/BudgetTracker.git)
#   BUDGET_TRACKER_REF  — ветка (по умолчанию main)
set -euo pipefail

REPO_URL="${BUDGET_TRACKER_REPO:-https://github.com/sttell/BudgetTracker.git}"
REF="${BUDGET_TRACKER_REF:-main}"

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }

# Запуск из уже скачанной копии (./install/install.sh) — ставим её же, иначе клонируем
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/../pyproject.toml" ] && [ -z "${BUDGET_TRACKER_DIR:-}" ]; then
  DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
else
  DIR="${BUDGET_TRACKER_DIR:-$HOME/BudgetTracker}"
fi

if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  say "Устанавливаю uv (менеджер Python)"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

if [ -d "$DIR/.git" ]; then
  say "Обновляю $DIR"
  git -C "$DIR" pull --ff-only || say "Не удалось обновить (локальные изменения?) — продолжаю с текущей версией"
elif [ -f "$DIR/pyproject.toml" ]; then
  say "Использую $DIR"
elif command -v git >/dev/null 2>&1; then
  say "Скачиваю BudgetTracker в $DIR"
  git clone --branch "$REF" "$REPO_URL" "$DIR"
else
  say "git не найден — скачиваю архив в $DIR"
  mkdir -p "$DIR"
  curl -fsSL "${REPO_URL%.git}/archive/refs/heads/$REF.tar.gz" | tar -xz --strip-components=1 -C "$DIR"
fi

say "Ставлю зависимости (Python скачается автоматически, если нужно)"
"$UV" sync --directory "$DIR" --no-dev

say "Подключаю к Claude"
"$UV" run --no-dev --directory "$DIR" python install/setup_claude.py --uv "$UV"
