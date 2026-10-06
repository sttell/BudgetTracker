# Установка BudgetTracker на Windows (PowerShell):
#   irm https://raw.githubusercontent.com/sttell/BudgetTracker/main/install/install.ps1 | iex
# Повторный запуск обновляет установку. Переменные окружения:
#   BUDGET_TRACKER_DIR  — куда установить (по умолчанию %USERPROFILE%\BudgetTracker)
#   BUDGET_TRACKER_REPO — git-репозиторий (по умолчанию https://github.com/sttell/BudgetTracker.git)
#   BUDGET_TRACKER_REF  — ветка (по умолчанию main)
$ErrorActionPreference = "Stop"

$RepoUrl = if ($env:BUDGET_TRACKER_REPO) { $env:BUDGET_TRACKER_REPO } else { "https://github.com/sttell/BudgetTracker.git" }
$Ref = if ($env:BUDGET_TRACKER_REF) { $env:BUDGET_TRACKER_REF } else { "main" }

function Say($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# Запуск из уже скачанной копии (.\install\install.ps1) — ставим её же, иначе клонируем
$Dir = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "..\pyproject.toml")) -and -not $env:BUDGET_TRACKER_DIR) {
    $Dir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
} elseif ($env:BUDGET_TRACKER_DIR) {
    $Dir = $env:BUDGET_TRACKER_DIR
} else {
    $Dir = Join-Path $env:USERPROFILE "BudgetTracker"
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Say "Устанавливаю uv (менеджер Python)"
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}
$Uv = (Get-Command uv).Source

if (Test-Path (Join-Path $Dir ".git")) {
    Say "Обновляю $Dir"
    git -C $Dir pull --ff-only
} elseif (Test-Path (Join-Path $Dir "pyproject.toml")) {
    Say "Использую $Dir"
} elseif (Get-Command git -ErrorAction SilentlyContinue) {
    Say "Скачиваю BudgetTracker в $Dir"
    git clone --branch $Ref $RepoUrl $Dir
} else {
    Say "git не найден — скачиваю архив в $Dir"
    $Zip = Join-Path $env:TEMP "BudgetTracker.zip"
    Invoke-WebRequest "$($RepoUrl -replace '\.git$', '')/archive/refs/heads/$Ref.zip" -OutFile $Zip
    $Tmp = Join-Path $env:TEMP "BudgetTracker-src"
    Expand-Archive $Zip -DestinationPath $Tmp -Force
    Move-Item (Get-ChildItem $Tmp | Select-Object -First 1).FullName $Dir
}

Say "Ставлю зависимости (Python скачается автоматически, если нужно)"
& $Uv sync --directory $Dir --no-dev

Say "Подключаю к Claude"
& $Uv run --no-dev --directory $Dir python install/setup_claude.py --uv $Uv
