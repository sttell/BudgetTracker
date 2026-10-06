"""MCP-интерфейс трекера для AI-агента (docs/DESIGN.md, раздел 8)."""

import functools
from datetime import date as Date, time as Time
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from budget.analytics import days_in_month
from budget.models import Currency, ExpenseInput
from budget.rates import RateUnavailable
from budget.service import Tracker, month_of
from budget.web.app import DEFAULT_PORT
from budget.webctl import ensure_running

INSTRUCTIONS = """\
Трекер личного бюджета пользователя. Данные меняются только через эти инструменты.

Перед работой вызови ensure_web_app (запустит веб-приложение, если оно не запущено) и get_settings: базовая валюта (в ней отвечай о суммах), валюта ввода по умолчанию,
категории, правила категорий, фиксированные траты.

Ввод трат:
- Диктовка/текст: сразу записывай (add_expenses, source="chat") и покажи таблицу записанного с суммами в базовой
  валюте. Дата по умолчанию — сегодня («вчера», «в пятницу» — пересчитай). Валюта не названа — валюта ввода
  по умолчанию. Если что-то неоднозначно — сначала спроси.
- Скриншот банковского приложения: извлеки название организации, сумму, валюту, дату и время каждой операции.
  Вызови add_expenses с dry_run=true (source="screenshot"), покажи черновик и возможные дубли, запиши после
  подтверждения пользователя.
- Не записывай переводы между своими счетами, пополнения и входящие переводы. Возврат — отрицательная сумма.
- Оплаты фиксированных трат (квартира, коммуналка и т.п. из get_settings) не добавляй как новые: найди
  трату месяца через list_expenses(kind="fixed") и, если сумма отличается, исправь её через update_expense.
- Тип: по умолчанию regular. irregular — только если пользователь так сказал; тогда уточни, входит ли трата
  в бюджет или она «сверх бюджета» (over_budget=true), если он этого не сказал.
- Категорию подбирай из списка категорий; если правило категории подобрало её само — оставь. Если пользователь
  поправил категорию у типичного места, предложи запомнить правило (set_category_rule).

После записи, правки или удаления трат ответ инструмента содержит budget_status (бюджет на сегодня) и page_url.
Всегда заканчивай ответ сводкой из budget_status в 2–3 строки: остаток на сегодня, неделю и месяц, а при
перерасходе — его сумму; затем ссылка page_url. Если ничего не записал (например, дубль) — всё равно вызови
get_budget_status и покажи ту же сводку.

Настройки (set_target, add/update/delete_fixed_expense, update_settings) меняй только по явной просьбе пользователя.
"""

mcp = MCPServer("budget-tracker", instructions=INSTRUCTIONS)
tracker = Tracker()


def tool(fn):
    """Ошибки валидации отдаём агенту текстом (иначе SDK скрывает их как сбой)."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, RateUnavailable, RuntimeError) as err:
            raise ToolError(str(err)) from err
    return mcp.tool()(wrapper)


def _month_bounds(day: Date) -> tuple[Date, Date]:
    return day.replace(day=1), day.replace(day=days_in_month(day))


def _after_write(days: set[str]) -> dict:
    """Бюджет на сегодня и страница затронутого дня (несколько дней — дашборд), чтобы агент не пропускал сводку."""
    url = f"http://localhost:{DEFAULT_PORT}"
    try:
        status = tracker.budget_status(None)
    except ValueError as err:  # трата уже записана — без таргета не роняем ответ
        status = {"error": str(err)}
    return {"budget_status": status,
            "page_url": f"{url}/day/{next(iter(days))}" if len(days) == 1 else f"{url}/"}


@tool
def ensure_web_app() -> dict:
    """Проверить, запущено ли веб-приложение трекера, и запустить его, если нет. Возвращает url и started
    (true — пришлось запустить). Страница дня: {url}/day/YYYY-MM-DD, дашборд: {url}/."""
    return ensure_running(tracker.storage.root)


@tool
def get_settings() -> dict:
    """Базовая валюта, валюта ввода, категории, правила категорий, шаблоны фиксированных трат, таргет текущего месяца."""
    target = tracker.target_for(month_of(Date.today()))
    return tracker.settings().model_dump(mode="json") | {
        "fixed_expenses": [t.model_dump(mode="json") for t in tracker.list_fixed()],
        "current_month_target": target.model_dump() if target else None,
        "today": Date.today().isoformat(),
    }


@tool
def add_expenses(expenses: list[ExpenseInput], dry_run: bool = False) -> dict:
    """Добавить траты пачкой. dry_run=true — только черновик без записи. В expenses для каждой траты — сумма
    в базовой валюте (amount_base), подобранная категория и possible_duplicates (уже записанные траты
    с той же датой, суммой и валютой). После записи (не dry_run) — ещё budget_status и page_url для сводки."""
    added = tracker.add_expenses(expenses, dry_run=dry_run)
    if dry_run:
        return {"expenses": added}
    return {"expenses": added} | _after_write({e["date"] for e in added})


@tool
def list_expenses(date_from: Date | None = None, date_to: Date | None = None,
                  kind: Literal["regular", "irregular", "fixed"] | None = None,
                  category: str | None = None, query: str | None = None) -> list[dict]:
    """Траты за период (по умолчанию — текущий месяц). category="uncategorized" — без категории.
    query ищет подстроку в названии и комментарии."""
    start, end = _month_bounds(Date.today())
    return tracker.list_expenses(date_from or start, date_to or end, kind, category, query)


@tool
def update_expense(expense_id: str, date: Date | None = None, time: Time | None = None, name: str | None = None,
                   amount: float | None = None, currency: Currency | None = None, category: str | None = None,
                   kind: Literal["regular", "irregular"] | None = None, over_budget: bool | None = None,
                   note: str | None = None, clear_category: bool = False) -> dict:
    """Исправить трату: меняются только переданные поля. clear_category=true — убрать категорию.
    Возвращает трату (expense), budget_status и page_url для сводки."""
    fields = {k: v for k, v in {
        "date": date, "time": time, "name": name, "amount": amount, "currency": currency,
        "category": category, "kind": kind, "over_budget": over_budget, "note": note,
    }.items() if v is not None}
    if clear_category:
        fields["category"] = None
    updated = tracker.update_expense(expense_id, **fields)
    return {"expense": updated} | _after_write({updated["date"]})


@tool
def delete_expense(expense_id: str) -> dict:
    """Удалить трату. Возвращает удалённую трату (expense), budget_status и page_url для сводки."""
    deleted = tracker.delete_expense(expense_id)
    return {"expense": deleted} | _after_write({deleted["date"]})


@tool
def get_budget_status(date: Date | None = None) -> dict:
    """Бюджет на дату (по умолчанию сегодня): остаток месяца, лимит на день, сколько осталось на сегодня
    и на неделю (до воскресенья, не дальше конца месяца), перерасход, сумма трат сверх бюджета."""
    return tracker.budget_status(date)


@tool
def get_summary(date_from: Date, date_to: Date,
                group_by: Literal["category", "name", "day", "kind"] = "category") -> dict:
    """Суммы трат за период в базовой валюте, сгруппированные по категории, названию, дню или типу."""
    return tracker.summary(date_from, date_to, group_by)


@tool
def get_month_report(month: str | None = None) -> dict:
    """Итог месяца (YYYY-MM, по умолчанию текущий): таргет, фиксированные, траты в бюджете, отклонение от
    таргета, траты сверх бюджета, всего; разбивки по типам и категориям; лимит и факт по дням."""
    return tracker.month_report(month or month_of(Date.today()))


@tool
def set_category_rule(pattern: str, category: str) -> list[dict]:
    """Запомнить правило: если название траты содержит pattern (без учёта регистра) — категория category."""
    return [r.model_dump() for r in tracker.set_category_rule(pattern, category)]


@tool
def set_rate(date: Date, currency: Literal["EUR", "USD"], rsd_per_unit: float) -> str:
    """Задать официальный курс НБС вручную (RSD за 1 единицу), если источник недоступен.
    Коэффициент реального курса применяется поверх него."""
    tracker.rates.set_rate(date, currency, rsd_per_unit)
    return "ok"


@tool
def set_real_rate(currency: Literal["EUR", "USD"], rsd_per_unit: float) -> dict:
    """Реальный курс обмена (RSD за 1 единицу) на сегодня. Сохраняется как коэффициент к курсу НБС и применяется
    ко всем датам: реальный курс = курс НБС на дату × коэффициент. Только по явной просьбе пользователя."""
    return {"currency": currency, "coefficient": tracker.set_real_rate(currency, rsd_per_unit)}


@tool
def set_target(amount: float, month: str | None = None, currency: Currency | None = None) -> dict:
    """Таргет на месяц (YYYY-MM, по умолчанию текущий); действует и на следующие месяцы, пока не задан новый.
    Только по явной просьбе пользователя."""
    return tracker.set_target(month or month_of(Date.today()), amount, currency).model_dump()


@tool
def add_fixed_expense(name: str, amount: float, currency: Currency | None = None, category: str | None = None,
                      since: str | None = None) -> dict:
    """Новый шаблон фиксированной ежемесячной траты (since — первый месяц YYYY-MM, по умолчанию текущий).
    Только по явной просьбе пользователя."""
    return tracker.add_fixed(name, amount, currency, category, since).model_dump()


@tool
def update_fixed_expense(fixed_id: str, name: str | None = None, amount: float | None = None,
                         currency: Currency | None = None, category: str | None = None) -> dict:
    """Изменить шаблон фиксированной траты; влияет на месяцы, где шаблон ещё не применён.
    Только по явной просьбе пользователя."""
    fields = {k: v for k, v in {"name": name, "amount": amount, "currency": currency, "category": category}.items()
              if v is not None}
    return tracker.update_fixed(fixed_id, **fields).model_dump()


@tool
def delete_fixed_expense(fixed_id: str) -> str:
    """Удалить шаблон фиксированной траты (уже созданные траты месяцев остаются). Только по явной просьбе."""
    tracker.delete_fixed(fixed_id)
    return "ok"


@tool
def update_settings(base_currency: Currency | None = None, input_currency: Currency | None = None) -> dict:
    """Сменить базовую валюту и/или валюту ввода по умолчанию. Только по явной просьбе пользователя."""
    return tracker.update_settings(base_currency, input_currency).model_dump(mode="json")


def main():
    mcp.run()
