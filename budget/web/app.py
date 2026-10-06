"""Веб-интерфейс трекера (docs/DESIGN.md, раздел 9)."""

import calendar
import os
from collections import defaultdict
from datetime import date as Date, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for

from budget.analytics import days_in_month
from budget.models import ExpenseInput
from budget.rates import RateUnavailable
from budget.service import Tracker, month_of, month_start

DEFAULT_PORT = 5050
HEALTH_TEXT = "budget-tracker ok"
SYMBOLS = {"EUR": "€", "USD": "$", "RSD": "дин."}
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября",
              "ноября", "декабря"]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь",
          "ноябрь", "декабрь"]


def parse_amount(text: str) -> float:
    try:
        return float(text.replace(",", ".").replace(" ", "").replace("\u202f", ""))
    except ValueError:
        raise ValueError(f"Не удалось разобрать сумму {text!r}") from None


def create_app(tracker: Tracker | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "local-only"
    tracker = tracker or Tracker()

    @app.template_filter("money")
    def money(value, currency=None):
        if value is None:
            return "—"
        text = f"{value:,.2f}".replace(",", " ")
        return f"{text} {SYMBOLS.get(currency or tracker.settings().base_currency, currency)}"

    @app.template_filter("num")
    def num(value) -> str:
        return f"{value:.2f}".rstrip("0").rstrip(".")

    @app.template_filter("month_title")
    def month_title(month: str) -> str:
        return f"{MONTHS[int(month[5:]) - 1].capitalize()} {month[:4]}"

    @app.template_filter("day_title")
    def day_title(day: str) -> str:
        d = Date.fromisoformat(day)
        return f"{d.day} {MONTHS_GEN[d.month - 1]}, {WEEKDAYS[d.weekday()]}"

    @app.context_processor
    def common():
        settings = tracker.settings()
        return {
            "settings": settings,
            "category_names": {c.id: c.name for c in settings.categories},
            "today": Date.today().isoformat(),
        }

    @app.errorhandler(ValueError)
    @app.errorhandler(RateUnavailable)
    def user_error(err):
        flash(str(err), "error")
        return redirect(request.referrer or url_for("dashboard"))

    def back(default: str):
        return redirect(request.form.get("next") or default)

    # --- дашборд ---------------------------------------------------------------------------

    @app.get("/healthz")
    def healthz():
        return HEALTH_TEXT

    @app.get("/")
    def dashboard():
        today = Date.today()
        month = month_of(today)
        if tracker.target_for(month) is None:
            return render_template("dashboard.html", status=None, month=month)
        status = tracker.budget_status(today)
        report = tracker.month_report(month)
        expenses = tracker.list_expenses(month_start(month), today.replace(day=days_in_month(today)))

        by_category = defaultdict(float)
        for e in expenses:
            if e["kind"] != "fixed":
                by_category[e["category"] or "uncategorized"] += e["amount_base"]

        dim = days_in_month(today)
        cumulative, total = [], 0.0
        for d in report["days"]:
            total += d["spent"]
            cumulative.append(round(total, 2))
        chart = {
            "labels": list(range(1, dim + 1)),
            "ideal": [round(status["pool"] * d / dim, 2) for d in range(1, dim + 1)],
            "cumulative": cumulative,
            "pool": status["pool"],
            "daily_spent": [d["spent"] for d in report["days"]],
            "daily_limit": [d["limit"] for d in report["days"]],
        }
        return render_template(
            "dashboard.html", month=month, status=status, report=report, chart=chart,
            categories=sorted(by_category.items(), key=lambda kv: -kv[1]),
            fixed=[e for e in expenses if e["kind"] == "fixed"],
            irregular=[e for e in expenses if e["kind"] == "irregular"],
        )

    # --- календарь и день ------------------------------------------------------------------

    def day_stats(month: str) -> dict[str, dict]:
        if tracker.target_for(month) is None:
            return {}
        return {d["date"]: d for d in tracker.month_report(month)["days"]}

    @app.get("/calendar")
    def calendar_view():
        month = request.args.get("month") or month_of(Date.today())
        first = month_start(month)
        last = first.replace(day=days_in_month(first))
        stats = day_stats(month)
        spent, over = defaultdict(float), defaultdict(float)
        for e in tracker.list_expenses(first, last):
            if e["kind"] == "irregular" and e["over_budget"]:
                over[e["date"]] += e["amount_base"]
            elif e["kind"] != "fixed":
                spent[e["date"]] += e["amount_base"]
        for day, st in stats.items():
            spent[day] = st["spent"]  # без поэлементного округления — совпадает с лимитом и страницей дня
        weeks = calendar.Calendar().monthdatescalendar(first.year, first.month)
        prev_month = month_of(first - timedelta(days=1))
        next_month = month_of(last + timedelta(days=1))
        return render_template("calendar.html", month=month, weeks=weeks, stats=stats, spent=spent, over=over,
                               weekdays=WEEKDAYS, prev_month=prev_month, next_month=next_month)

    @app.get("/day/<day>")
    def day_view(day: str):
        d = Date.fromisoformat(day)
        expenses = tracker.list_expenses(d, d)
        stat = day_stats(month_of(d)).get(day)
        return render_template("day.html", day=day, expenses=expenses, stat=stat,
                               prev_day=(d - timedelta(days=1)).isoformat(),
                               next_day=(d + timedelta(days=1)).isoformat())

    @app.post("/expenses/add")
    def add_expense():
        f = request.form
        kind = f.get("kind", "regular")
        tracker.add_expenses([ExpenseInput(
            date=f["date"], time=f.get("time") or None, name=f["name"].strip(),
            amount=parse_amount(f["amount"]), currency=f.get("currency") or None,
            category=f.get("category") or None, kind=kind, over_budget=kind == "irregular" and "over_budget" in f,
            note=f.get("note", "").strip(), source="manual",
        )])
        flash(f"Добавлено: {f['name'].strip()}", "ok")
        return back(url_for("day_view", day=f["date"]))

    @app.post("/expenses/<expense_id>/edit")
    def edit_expense(expense_id: str):
        f = request.form
        fields = {
            "date": f["date"], "time": f.get("time") or None, "name": f["name"].strip(),
            "amount": parse_amount(f["amount"]), "currency": f["currency"],
            "category": f.get("category") or None, "note": f.get("note", "").strip(),
        }
        if f.get("kind") in ("regular", "irregular"):
            fields["kind"] = f["kind"]
            fields["over_budget"] = f["kind"] == "irregular" and "over_budget" in f
        tracker.update_expense(expense_id, **fields)
        flash("Сохранено", "ok")
        return back(url_for("day_view", day=f["date"]))

    @app.post("/expenses/<expense_id>/delete")
    def delete_expense(expense_id: str):
        removed = tracker.delete_expense(expense_id)
        flash(f"Удалено: {removed['name']}", "ok")
        return back(url_for("day_view", day=removed["date"]))

    # --- операции --------------------------------------------------------------------------

    @app.get("/expenses")
    def expenses_view():
        today = Date.today()
        a = request.args
        date_from = Date.fromisoformat(a["from"]) if a.get("from") else today.replace(day=1)
        date_to = Date.fromisoformat(a["to"]) if a.get("to") else today.replace(day=days_in_month(today))
        expenses = tracker.list_expenses(date_from, date_to, a.get("kind") or None, a.get("category") or None,
                                         a.get("q") or None)
        expenses.sort(key=lambda e: (e["date"], e["time"] or ""), reverse=True)
        return render_template("expenses.html", expenses=expenses, date_from=date_from.isoformat(),
                               date_to=date_to.isoformat(), filters=a,
                               total=sum(e["amount_base"] for e in expenses))

    @app.post("/expenses/bulk-category")
    def bulk_category():
        ids = request.form.getlist("ids")
        category = request.form.get("category") or None
        for expense_id in ids:
            tracker.update_expense(expense_id, category=category)
        flash(f"Категория изменена у {len(ids)} трат", "ok")
        return back(url_for("expenses_view"))

    # --- настройки -------------------------------------------------------------------------

    @app.get("/settings")
    def settings_view():
        month = month_of(Date.today())
        today = Date.today()
        rates = [{"currency": cur, "official": tracker.rates.rsd_per(cur, today),
                  "real": tracker.rates.effective(cur, today),
                  "coef": tracker.settings().rate_adjustments.get(cur, 1.0)} for cur in ("USD", "EUR")]
        return render_template("settings.html", month=month, target=tracker.target_for(month),
                               fixed=tracker.list_fixed(), rates=rates)

    @app.post("/settings/currencies")
    def save_currencies():
        tracker.update_settings(request.form["base_currency"], request.form["input_currency"])
        flash("Валюты сохранены", "ok")
        return redirect(url_for("settings_view"))

    @app.post("/settings/rates")
    def save_rates():
        for cur in ("USD", "EUR"):
            if request.form.get(cur):
                tracker.set_real_rate(cur, parse_amount(request.form[cur]))
        flash("Коэффициенты курса сохранены", "ok")
        return redirect(url_for("settings_view"))

    @app.post("/settings/target")
    def save_target():
        f = request.form
        tracker.set_target(f["month"], parse_amount(f["amount"]), f["currency"])
        flash("Таргет сохранён", "ok")
        return redirect(url_for("settings_view"))

    @app.post("/settings/fixed")
    def add_fixed():
        f = request.form
        tracker.add_fixed(f["name"].strip(), parse_amount(f["amount"]), f["currency"],
                          f.get("category") or None)
        flash("Фиксированная трата добавлена", "ok")
        return redirect(url_for("settings_view"))

    @app.post("/settings/fixed/<fixed_id>")
    def edit_fixed(fixed_id: str):
        f = request.form
        if "delete" in f:
            tracker.delete_fixed(fixed_id)
        else:
            tracker.update_fixed(fixed_id, name=f["name"].strip(), currency=f["currency"],
                                 amount=parse_amount(f["amount"]),
                                 category=f.get("category") or None)
        flash("Сохранено", "ok")
        return redirect(url_for("settings_view"))

    @app.post("/settings/rules")
    def add_rule():
        tracker.set_category_rule(request.form["pattern"].strip(), request.form["category"])
        flash("Правило сохранено", "ok")
        return redirect(url_for("settings_view") + "#rules")

    @app.post("/settings/rules/delete")
    def delete_rule():
        tracker.delete_category_rule(request.form["pattern"])
        return redirect(url_for("settings_view") + "#rules")

    @app.post("/settings/categories")
    def save_category():
        f = request.form
        if f.get("id"):
            tracker.update_category(f["id"], f["name"].strip(), f["color"])
        else:
            tracker.add_category(f["name"].strip(), f["color"])
        flash("Категория сохранена", "ok")
        return redirect(url_for("settings_view") + "#categories")

    return app


def main():
    create_app().run(host="127.0.0.1", port=int(os.environ.get("BUDGET_WEB_PORT", DEFAULT_PORT)), debug=False)
