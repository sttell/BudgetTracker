from datetime import date

import pytest

from budget.models import ExpenseInput
from budget.rates import RateUnavailable
from budget.service import Tracker, month_of

RATES = {"EUR": 117.5, "USD": 104.4}
TODAY = date.today()
MONTH = month_of(TODAY)


@pytest.fixture
def tracker(tmp_path):
    return Tracker(tmp_path, fetch_rate=lambda code, day: RATES[code])


def expense(name="Maxi", amount=1175.0, day=TODAY, **kw):
    return ExpenseInput(date=day, name=name, amount=amount, source="chat", **kw)


def test_add_converts_to_base_and_defaults(tracker):
    [e] = tracker.add_expenses([expense()])
    assert e["currency"] == "RSD"
    assert e["kind"] == "regular"
    assert e["amount_base"] == 10.0
    assert tracker.list_expenses(TODAY, TODAY)[0]["id"] == e["id"]


def test_dry_run_does_not_write_and_flags_duplicates(tracker):
    tracker.add_expenses([expense()])
    [draft] = tracker.add_expenses([expense(name="MAXI 123 BEOGRAD")], dry_run=True)
    assert len(draft["possible_duplicates"]) == 1
    assert len(tracker.list_expenses(TODAY, TODAY)) == 1


def test_category_rules(tracker):
    tracker.set_category_rule("maxi", "groceries")
    [e] = tracker.add_expenses([expense(name="MAXI 123")])
    assert e["category"] == "groceries"
    with pytest.raises(ValueError, match="Неизвестная категория"):
        tracker.add_expenses([expense(category="nope")])


def test_over_budget_only_for_irregular(tracker):
    with pytest.raises(ValueError, match="нерегулярной"):
        tracker.add_expenses([expense(over_budget=True)])


def test_fixed_applied_once_and_feed_budget(tracker):
    tracker.set_target(MONTH, 3000)
    tracker.add_fixed("Квартира", 1500, since=MONTH)
    fixed = tracker.list_expenses(TODAY.replace(day=1), TODAY, kind="fixed")
    assert [f["amount"] for f in fixed] == [1500]
    tracker.delete_expense(fixed[0]["id"])
    assert tracker.list_expenses(TODAY.replace(day=1), TODAY, kind="fixed") == []

    tracker.add_fixed("Зал", 280, since=MONTH)
    assert tracker.budget_status(TODAY)["fixed"] == 280


def test_fixed_not_created_without_target(tracker):
    tracker.add_fixed("Квартира", 1500, since=MONTH)
    assert tracker.list_expenses(TODAY.replace(day=1), TODAY, kind="fixed") == []


def test_update_moves_between_months_and_validates(tracker):
    [e] = tracker.add_expenses([expense()])
    moved = tracker.update_expense(e["id"], date=date(2025, 1, 15), kind="irregular", over_budget=True)
    assert moved["date"] == "2025-01-15"
    assert tracker.list_expenses(TODAY, TODAY) == []
    assert len(tracker.list_expenses(date(2025, 1, 1), date(2025, 1, 31))) == 1
    with pytest.raises(ValueError):
        tracker.update_expense(e["id"], kind="fixed")
    with pytest.raises(ValueError, match="Нельзя менять"):
        tracker.update_expense(e["id"], id="x")


def test_base_currency_switch_recomputes(tracker):
    tracker.add_expenses([expense(amount=10, currency="EUR")])
    tracker.update_settings(base_currency="USD")
    [e] = tracker.list_expenses(TODAY, TODAY)
    assert e["amount_base"] == round(10 * 117.5 / 104.4, 2)


def test_rate_fallback_and_manual(tmp_path):
    def offline(code, day):
        raise OSError("offline")

    tracker = Tracker(tmp_path, fetch_rate=offline)
    with pytest.raises(RateUnavailable):
        tracker.add_expenses([expense()])
    tracker.rates.set_rate(date(2026, 1, 1), "EUR", 117.0)
    [e] = tracker.add_expenses([expense(amount=117)])
    assert e["amount_base"] == 1.0


def test_target_carries_forward(tracker):
    tracker.set_target("2026-01", 3000)
    assert tracker.target_for("2026-05").amount == 3000
    assert tracker.target_for("2025-12") is None


def test_real_rate_coefficient(tracker):
    coef = tracker.set_real_rate("USD", 101.0, TODAY)
    assert coef == pytest.approx(101.0 / 104.4)
    tracker.set_real_rate("EUR", 117.8, TODAY)
    [e] = tracker.add_expenses([expense(amount=101, currency="USD")])
    assert e["amount_base"] == round(101 * 101 / 117.8, 2)  # 101 $ × 101 RSD/$ ÷ 117.8 RSD/€
    assert tracker.rates.rsd_per("USD", TODAY) == 104.4  # в кеше остаётся официальный курс
