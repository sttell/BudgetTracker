from datetime import date

import pytest

from budget.analytics import Row, budget_status, day_history, month_report


def row(day, amount, kind="regular", over_budget=False, name="x"):
    return Row(date(2026, 10, day), name, None, kind, over_budget, amount)


FIXED = [row(1, 1500, "fixed"), row(1, 200, "fixed"), row(1, 280, "fixed")]


def test_design_doc_example():
    # docs/DESIGN.md, раздел 3: таргет 3000, фиксированные 1980, октябрь 31 день
    rows = FIXED + [row(1, 50), row(2, 10)]
    limits = [d["limit"] for d in day_history(rows, 3000, date(2026, 10, 3))]
    assert limits == pytest.approx([1020 / 31, 970 / 30, 960 / 29])


def test_irregular_in_budget_reduces_limits_over_budget_does_not():
    base = budget_status(FIXED, 3000, date(2026, 10, 11))["day_limit"]
    in_budget = budget_status(FIXED + [row(10, 300, "irregular")], 3000, date(2026, 10, 11))
    over = budget_status(FIXED + [row(10, 300, "irregular", over_budget=True)], 3000, date(2026, 10, 11))
    assert in_budget["day_limit"] == pytest.approx(base - 300 / 21)
    assert over["day_limit"] == pytest.approx(base)
    assert over["over_budget_total"] == 300


def test_today_week_and_overspend():
    # 2026-10-28 — среда; до воскресенья 5 дней, но месяц кончается 31-го → 4 дня
    status = budget_status(FIXED + [row(5, 1100), row(28, 20)], 3000, date(2026, 10, 28))
    assert status["day_limit"] == 0
    assert status["month_overspent"] == pytest.approx(100)
    assert status["week_days_left"] == 4
    assert status["today_remaining"] == -20


def test_week_inside_month():
    status = budget_status(FIXED + [row(7, 5)], 3000, date(2026, 10, 7))  # среда
    assert status["week_days_left"] == 5
    assert status["week_end"] == "2026-10-11"
    assert status["week_remaining"] == pytest.approx(status["day_limit"] * 5 - 5)


def test_month_report_totals():
    rows = FIXED + [row(3, 100), row(4, 50, "irregular"), row(5, 400, "irregular", over_budget=True)]
    report = month_report(rows, 3000, date(2026, 10, 31))
    assert report["fixed"] == 1980
    assert report["in_budget"] == 150
    assert report["vs_target"] == -870
    assert report["over_budget"] == 400
    assert report["total"] == 2530
    assert len(report["days"]) == 31
