"""Единственная точка чтения и записи данных для веба и MCP (docs/DESIGN.md)."""

import os
import uuid
from datetime import date as Date
from pathlib import Path

from budget import analytics
from budget.analytics import Row
from budget.models import (
    Category,
    CategoryRule,
    Expense,
    ExpenseInput,
    FixedTemplate,
    Money,
    MonthFile,
    Settings,
)
from budget.rates import Rates, fetch_nbs
from budget.storage import Storage

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
EDITABLE_FIELDS = {"date", "time", "name", "amount", "currency", "category", "kind", "over_budget", "note"}


def month_of(day: Date) -> str:
    return day.strftime("%Y-%m")


def month_start(month: str) -> Date:
    return Date.fromisoformat(f"{month}-01")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def rounded(obj):
    if isinstance(obj, float):
        return round(obj, 2)
    if isinstance(obj, dict):
        return {k: rounded(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rounded(v) for v in obj]
    return obj


class Tracker:
    def __init__(self, data_dir: Path | None = None, fetch_rate=fetch_nbs):
        self.storage = Storage(data_dir or Path(os.environ.get("BUDGET_DATA_DIR", DEFAULT_DATA_DIR)))
        self.rates = Rates(self.storage, fetch_rate, lambda: self.settings().rate_adjustments)

    # --- настройки -------------------------------------------------------------------------

    def settings(self) -> Settings:
        return Settings.model_validate(self.storage.read("settings.json", {}))

    def _save_settings(self, settings: Settings) -> None:
        self.storage.write("settings.json", settings.model_dump(mode="json"))

    def update_settings(self, base_currency: str | None = None, input_currency: str | None = None) -> Settings:
        with self.storage.lock():
            current = self.settings().model_dump()
            if base_currency:
                current["base_currency"] = base_currency
            if input_currency:
                current["input_currency"] = input_currency
            settings = Settings.model_validate(current)
            self._save_settings(settings)
        return settings

    def set_real_rate(self, currency: str, rsd_per_unit: float, day: Date | None = None) -> float:
        """Сохраняет коэффициент = реальный курс / курс НБС на дату (по умолчанию сегодня)."""
        if currency == "RSD":
            raise ValueError("Курс задаётся для EUR или USD")
        if rsd_per_unit <= 0:
            raise ValueError("Курс должен быть положительным")
        coef = rsd_per_unit / self.rates.rsd_per(currency, day or Date.today())
        with self.storage.lock():
            settings = self.settings()
            settings.rate_adjustments = settings.rate_adjustments | {currency: coef}
            self._save_settings(settings)
        return coef

    def _check_category(self, category: str | None, settings: Settings) -> None:
        ids = [c.id for c in settings.categories]
        if category is not None and category not in ids:
            raise ValueError(f"Неизвестная категория {category!r}; допустимые: {', '.join(ids)}")

    def set_category_rule(self, pattern: str, category: str) -> list[CategoryRule]:
        with self.storage.lock():
            settings = self.settings()
            self._check_category(category, settings)
            rules = [r for r in settings.category_rules if r.pattern.lower() != pattern.lower()]
            rules.append(CategoryRule(pattern=pattern, category=category))
            settings.category_rules = rules
            self._save_settings(settings)
        return rules

    def delete_category_rule(self, pattern: str) -> None:
        with self.storage.lock():
            settings = self.settings()
            settings.category_rules = [r for r in settings.category_rules if r.pattern.lower() != pattern.lower()]
            self._save_settings(settings)

    def add_category(self, name: str, color: str) -> Category:
        with self.storage.lock():
            settings = self.settings()
            category = Category(id=_new_id("c"), name=name, color=color)
            settings.categories.append(category)
            self._save_settings(settings)
        return category

    def update_category(self, category_id: str, name: str, color: str) -> None:
        with self.storage.lock():
            settings = self.settings()
            self._check_category(category_id, settings)
            settings.categories = [Category(id=c.id, name=name, color=color) if c.id == category_id else c
                                   for c in settings.categories]
            self._save_settings(settings)

    def categorize(self, name: str, settings: Settings) -> str | None:
        """Самое длинное правило, чей шаблон входит в название (без учёта регистра)."""
        matches = [r for r in settings.category_rules if r.pattern.lower() in name.lower()]
        return max(matches, key=lambda r: len(r.pattern)).category if matches else None

    # --- таргет ----------------------------------------------------------------------------

    def set_target(self, month: str, amount: float, currency: str | None = None) -> Money:
        target = Money(amount=amount, currency=currency or self.settings().base_currency)
        month_start(month)  # валидация формата
        with self.storage.lock():
            targets = self.storage.read("targets.json", {})
            targets[month] = target.model_dump()
            self.storage.write("targets.json", dict(sorted(targets.items())))
        return target

    def target_for(self, month: str) -> Money | None:
        """Таргет действует с указанного месяца, пока не задан новый."""
        targets = self.storage.read("targets.json", {})
        months = [m for m in targets if m <= month]
        return Money.model_validate(targets[max(months)]) if months else None

    # --- фиксированные траты ---------------------------------------------------------------

    def list_fixed(self) -> list[FixedTemplate]:
        return [FixedTemplate.model_validate(t) for t in self.storage.read("fixed.json", [])]

    def _save_fixed(self, templates: list[FixedTemplate]) -> None:
        self.storage.write("fixed.json", [t.model_dump(mode="json") for t in templates])

    def add_fixed(self, name: str, amount: float, currency: str | None = None, category: str | None = None,
                  since: str | None = None) -> FixedTemplate:
        settings = self.settings()
        self._check_category(category, settings)
        template = FixedTemplate(id=_new_id("f"), name=name, amount=amount,
                                 currency=currency or settings.base_currency, category=category,
                                 since=since or month_of(Date.today()))
        with self.storage.lock():
            self._save_fixed(self.list_fixed() + [template])
        return template

    def update_fixed(self, template_id: str, **fields) -> FixedTemplate:
        with self.storage.lock():
            templates = self.list_fixed()
            idx = next((i for i, t in enumerate(templates) if t.id == template_id), None)
            if idx is None:
                raise ValueError(f"Фиксированная трата {template_id!r} не найдена")
            self._check_category(fields.get("category"), self.settings())
            templates[idx] = FixedTemplate.model_validate(templates[idx].model_dump() | fields)
            self._save_fixed(templates)
        return templates[idx]

    def delete_fixed(self, template_id: str) -> None:
        with self.storage.lock():
            templates = self.list_fixed()
            if not any(t.id == template_id for t in templates):
                raise ValueError(f"Фиксированная трата {template_id!r} не найдена")
            self._save_fixed([t for t in templates if t.id != template_id])

    # --- месяцы ----------------------------------------------------------------------------

    def _read_month(self, month: str) -> MonthFile:
        return MonthFile.model_validate(self.storage.read(f"expenses/{month}.json", {}))

    def _write_month(self, month: str, data: MonthFile) -> None:
        data.expenses.sort(key=lambda e: (e.date, e.time is None, e.time or ""))
        self.storage.write(f"expenses/{month}.json", data.model_dump(mode="json"))

    def _month(self, month: str) -> MonthFile:
        """Траты месяца; в наступившем месяце с таргетом создаёт фиксированные траты из ещё не применённых шаблонов."""
        data = self._read_month(month)
        if month > month_of(Date.today()) or self.target_for(month) is None:
            return data
        pending = [t for t in self.list_fixed() if t.since <= month and t.id not in data.fixed_applied]
        if not pending:
            return data
        with self.storage.lock():
            data = self._read_month(month)
            for t in pending:
                if t.id in data.fixed_applied:
                    continue
                data.expenses.append(Expense(
                    id=_new_id("e"), date=month_start(month), name=t.name, amount=t.amount, currency=t.currency,
                    category=t.category, kind="fixed", source="fixed", fixed_id=t.id,
                ))
                data.fixed_applied.append(t.id)
            self._write_month(month, data)
        return data

    def _months_between(self, date_from: Date, date_to: Date) -> list[str]:
        first, last = month_of(date_from), month_of(date_to)
        stored = set(self.storage.list("expenses"))
        stored.add(month_of(Date.today()))
        return sorted(m for m in stored if first <= m <= last)

    # --- траты -----------------------------------------------------------------------------

    def _base(self, e: Expense, base_currency: str) -> float:
        return self.rates.convert(e.amount, e.currency, base_currency, e.date)

    def view(self, e: Expense, base_currency: str) -> dict:
        return rounded(e.model_dump(mode="json") | {"amount_base": self._base(e, base_currency)})

    def add_expenses(self, items: list[ExpenseInput], dry_run: bool = False) -> list[dict]:
        """Возвращает траты с суммой в базовой валюте и возможными дублями (та же дата, сумма и валюта)."""
        settings = self.settings()
        prepared = []
        for i, item in enumerate(items):
            self._check_category(item.category, settings)
            try:
                expense = Expense(
                    id=_new_id("e"), **item.model_dump(exclude={"currency", "category"}),
                    currency=item.currency or settings.input_currency,
                    category=item.category or self.categorize(item.name, settings),
                )
            except ValueError as err:
                raise ValueError(f"Трата #{i + 1} ({item.name}): {err}") from err
            prepared.append(expense)

        result = []
        for i, e in enumerate(prepared):
            same = [x for x in self._month(month_of(e.date)).expenses + prepared[:i]
                    if (x.date, x.amount, x.currency) == (e.date, e.amount, e.currency)]
            result.append(self.view(e, settings.base_currency)
                          | {"possible_duplicates": [self.view(x, settings.base_currency) for x in same]})
        if not dry_run:
            with self.storage.lock():
                for month in sorted({month_of(e.date) for e in prepared}):
                    data = self._month(month)
                    data.expenses += [e for e in prepared if month_of(e.date) == month]
                    self._write_month(month, data)
        return result

    def list_expenses(self, date_from: Date, date_to: Date, kind: str | None = None, category: str | None = None,
                      query: str | None = None) -> list[dict]:
        base = self.settings().base_currency
        found = []
        for month in self._months_between(date_from, date_to):
            for e in self._month(month).expenses:
                if not (date_from <= e.date <= date_to):
                    continue
                if kind and e.kind != kind:
                    continue
                if category and (e.category or "uncategorized") != category:
                    continue
                if query and query.lower() not in f"{e.name} {e.note}".lower():
                    continue
                found.append(self.view(e, base))
        return found

    def _find(self, expense_id: str) -> tuple[str, MonthFile, int]:
        for month in self.storage.list("expenses"):
            data = self._read_month(month)
            for idx, e in enumerate(data.expenses):
                if e.id == expense_id:
                    return month, data, idx
        raise ValueError(f"Трата {expense_id!r} не найдена")

    def update_expense(self, expense_id: str, **fields) -> dict:
        unknown = set(fields) - EDITABLE_FIELDS
        if unknown:
            raise ValueError(f"Нельзя менять поля: {', '.join(sorted(unknown))}")
        settings = self.settings()
        self._check_category(fields.get("category"), settings)
        with self.storage.lock():
            month, data, idx = self._find(expense_id)
            old = data.expenses[idx]
            if "kind" in fields and (fields["kind"] == "fixed") != (old.kind == "fixed"):
                raise ValueError("Фиксированные траты создаются только из шаблонов")
            updated = Expense.model_validate(old.model_dump() | fields)
            del data.expenses[idx]
            new_month = month_of(updated.date)
            if new_month == month:
                data.expenses.append(updated)
                self._write_month(month, data)
            else:
                self._write_month(month, data)
                target = self._month(new_month)
                target.expenses.append(updated)
                self._write_month(new_month, target)
        return self.view(updated, settings.base_currency)

    def delete_expense(self, expense_id: str) -> dict:
        with self.storage.lock():
            month, data, idx = self._find(expense_id)
            removed = data.expenses.pop(idx)
            self._write_month(month, data)
        return self.view(removed, self.settings().base_currency)

    # --- бюджет и аналитика ----------------------------------------------------------------

    def _rows(self, expenses: list[Expense], base_currency: str) -> list[Row]:
        return [Row(e.date, e.name, e.category, e.kind, e.over_budget, self._base(e, base_currency))
                for e in expenses]

    def _target_base(self, month: str, base_currency: str) -> float:
        target = self.target_for(month)
        if target is None:
            raise ValueError(f"Таргет на {month} не задан")
        return self.rates.convert(target.amount, target.currency, base_currency, month_start(month))

    def budget_status(self, day: Date | None = None) -> dict:
        day = day or Date.today()
        month = month_of(day)
        base = self.settings().base_currency
        target = self._target_base(month, base)
        rows = self._rows(self._month(month).expenses, base)
        return rounded({"currency": base} | analytics.budget_status(rows, target, day))

    def month_report(self, month: str) -> dict:
        base = self.settings().base_currency
        target = self._target_base(month, base)
        rows = self._rows(self._month(month).expenses, base)
        today = Date.today()
        last = month_start(month).replace(day=analytics.days_in_month(month_start(month)))
        upto = min(last, today) if month_of(today) == month else last
        return rounded({"month": month, "currency": base} | analytics.month_report(rows, target, upto))

    def summary(self, date_from: Date, date_to: Date, group_by: str) -> dict:
        base = self.settings().base_currency
        expenses = [e for m in self._months_between(date_from, date_to) for e in self._month(m).expenses
                    if date_from <= e.date <= date_to]
        return rounded({"currency": base, "groups": analytics.summarize(self._rows(expenses, base), group_by)})
