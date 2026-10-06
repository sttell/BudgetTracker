from datetime import date

import pytest

from budget.service import Tracker, month_of
from budget.web.app import create_app

TODAY = date.today()
MONTH = month_of(TODAY)


@pytest.fixture
def tracker(tmp_path):
    return Tracker(tmp_path, fetch_rate=lambda code, day: {"EUR": 117.5, "USD": 104.4}[code])


@pytest.fixture
def client(tracker):
    return create_app(tracker).test_client()


def test_dashboard_without_target(client):
    assert "Таргет на месяц не задан" in client.get("/").text


def test_settings_then_dashboard(client, tracker):
    client.post("/settings/target", data={"month": MONTH, "amount": "3 000", "currency": "EUR"})
    client.post("/settings/fixed", data={"name": "Квартира", "amount": "1500", "currency": "EUR", "category": "housing"})
    client.post("/settings/currencies", data={"base_currency": "EUR", "input_currency": "RSD"})
    page = client.get("/").text
    assert "Сегодня можно потратить" in page
    assert "Квартира" in page
    for path in ["/calendar", f"/day/{TODAY}", "/expenses", "/settings"]:
        assert client.get(path).status_code == 200, path


def test_add_edit_delete_expense(client, tracker):
    day = TODAY.isoformat()
    client.post("/expenses/add", data={"date": day, "name": "Шаурма", "amount": "1175,0", "currency": "RSD",
                                       "kind": "irregular", "over_budget": "on"})
    [e] = tracker.list_expenses(TODAY, TODAY)
    assert (e["amount_base"], e["kind"], e["over_budget"], e["source"]) == (10.0, "irregular", True, "manual")

    client.post(f"/expenses/{e['id']}/edit", data={"date": day, "name": "Шаурма", "amount": "1175", "currency": "RSD",
                                                   "category": "restaurants", "kind": "regular", "over_budget": "on"})
    [e] = tracker.list_expenses(TODAY, TODAY)
    assert (e["category"], e["kind"], e["over_budget"]) == ("restaurants", "regular", False)

    client.post("/expenses/bulk-category", data={"ids": [e["id"]], "category": "coffee"})
    assert tracker.list_expenses(TODAY, TODAY)[0]["category"] == "coffee"

    client.post(f"/expenses/{e['id']}/delete")
    assert tracker.list_expenses(TODAY, TODAY) == []


def test_invalid_input_flashes_error(client, tracker):
    resp = client.post("/expenses/add", data={"date": TODAY.isoformat(), "name": "x", "amount": "abc"},
                       follow_redirects=True)
    assert "Не удалось разобрать сумму" in resp.text
    assert tracker.list_expenses(TODAY, TODAY) == []
