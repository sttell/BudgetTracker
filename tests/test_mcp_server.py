from datetime import date

import pytest

from budget import mcp_server
from budget.models import ExpenseInput
from budget.service import Tracker

TODAY = date.today()


@pytest.fixture(autouse=True)
def tracker(tmp_path, monkeypatch):
    tracker = Tracker(tmp_path, fetch_rate=lambda code, day: {"EUR": 117.5, "USD": 104.4}[code])
    monkeypatch.setattr(mcp_server, "tracker", tracker)
    tracker.set_target(TODAY.strftime("%Y-%m"), 1000, "EUR")
    return tracker


def expense(day=TODAY):
    return ExpenseInput(date=day, name="Такси", amount=1000, source="chat")


def test_write_tools_return_budget_status_and_page():
    added = mcp_server.add_expenses([expense()])
    assert added["budget_status"]["date"] == TODAY.isoformat()
    assert added["page_url"].endswith(f"/day/{TODAY.isoformat()}")
    e = added["expenses"][0]

    updated = mcp_server.update_expense(e["id"], amount=500)
    assert updated["expense"]["amount"] == 500 and "budget_status" in updated

    deleted = mcp_server.delete_expense(e["id"])
    assert deleted["expense"]["id"] == e["id"] and "budget_status" in deleted


def test_dry_run_has_no_status_and_several_days_link_dashboard():
    assert mcp_server.add_expenses([expense()], dry_run=True).keys() == {"expenses"}
    added = mcp_server.add_expenses([expense(), expense(TODAY.replace(day=1) if TODAY.day > 1 else TODAY.replace(day=2))])
    assert added["page_url"].endswith(":5050/")


def test_write_without_target_still_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_server, "tracker", Tracker(tmp_path / "empty", fetch_rate=lambda code, day: 117.5))
    added = mcp_server.add_expenses([expense()])
    assert len(added["expenses"]) == 1 and "не задан" in added["budget_status"]["error"]
