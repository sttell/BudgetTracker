"""Логика бюджета и агрегаты — чистые функции над тратами в базовой валюте (docs/DESIGN.md, раздел 3)."""

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as Date, timedelta


@dataclass(frozen=True)
class Row:
    date: Date
    name: str
    category: str | None
    kind: str
    over_budget: bool
    amount: float  # в базовой валюте

    @property
    def in_budget(self) -> bool:
        return self.kind == "regular" or (self.kind == "irregular" and not self.over_budget)


def days_in_month(day: Date) -> int:
    return calendar.monthrange(day.year, day.month)[1]


def _pool(rows: list[Row], target: float) -> float:
    return target - sum(r.amount for r in rows if r.kind == "fixed")


def _spent_by_day(rows: list[Row]) -> dict[Date, float]:
    spent = defaultdict(float)
    for r in rows:
        if r.in_budget:
            spent[r.date] += r.amount
    return spent


def _limit(pool: float, spent_before: float, day: Date) -> float:
    days_left = days_in_month(day) - day.day + 1
    return max(0.0, pool - spent_before) / days_left


def day_history(rows: list[Row], target: float, upto: Date) -> list[dict]:
    """Лимит и факт по каждому дню месяца с 1-го числа по upto включительно."""
    pool = _pool(rows, target)
    spent = _spent_by_day(rows)
    history, spent_before = [], 0.0
    for d in range(1, upto.day + 1):
        day = upto.replace(day=d)
        limit = _limit(pool, spent_before, day)
        history.append({"date": day.isoformat(), "limit": limit, "spent": spent[day], "diff": limit - spent[day]})
        spent_before += spent[day]
    return history


def budget_status(rows: list[Row], target: float, today: Date) -> dict:
    """rows — траты месяца, в котором находится today."""
    pool = _pool(rows, target)
    spent = _spent_by_day(rows)
    spent_before = sum(v for d, v in spent.items() if d < today)
    limit = _limit(pool, spent_before, today)
    week_days = min(6 - today.weekday(), days_in_month(today) - today.day) + 1
    month_remaining = pool - spent_before - spent[today]
    return {
        "date": today.isoformat(),
        "target": target,
        "fixed": target - pool,
        "pool": pool,
        "spent_in_budget": spent_before + spent[today],
        "month_remaining": month_remaining,
        "month_overspent": max(0.0, -month_remaining),
        "day_limit": limit,
        "spent_today": spent[today],
        "today_remaining": limit - spent[today],
        "week_days_left": week_days,
        "week_end": (today + timedelta(days=week_days - 1)).isoformat(),
        "week_remaining": limit * week_days - spent[today],
        "over_budget_total": sum(r.amount for r in rows if r.kind == "irregular" and r.over_budget),
    }


def month_report(rows: list[Row], target: float, upto: Date) -> dict:
    fixed = sum(r.amount for r in rows if r.kind == "fixed")
    in_budget = sum(r.amount for r in rows if r.in_budget)
    over_budget = sum(r.amount for r in rows if r.kind == "irregular" and r.over_budget)
    return {
        "target": target,
        "fixed": fixed,
        "in_budget": in_budget,
        "total_in_budget": fixed + in_budget,
        "vs_target": fixed + in_budget - target,
        "over_budget": over_budget,
        "total": fixed + in_budget + over_budget,
        "by_kind": summarize(rows, "kind"),
        "by_category": summarize(rows, "category"),
        "days": day_history(rows, target, upto),
    }


def summarize(rows: list[Row], group_by: str) -> list[dict]:
    key = {
        "category": lambda r: r.category or "uncategorized",
        "name": lambda r: r.name,
        "day": lambda r: r.date.isoformat(),
        "kind": lambda r: "irregular_over_budget" if r.kind == "irregular" and r.over_budget else r.kind,
    }[group_by]
    groups = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for r in rows:
        g = groups[key(r)]
        g["amount"] += r.amount
        g["count"] += 1
    result = [{"key": k, **v} for k, v in groups.items()]
    if group_by == "day":
        return sorted(result, key=lambda g: g["key"])
    return sorted(result, key=lambda g: -g["amount"])
