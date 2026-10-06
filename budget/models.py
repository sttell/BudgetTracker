from datetime import date as Date, time as Time
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Currency = Literal["RSD", "EUR", "USD"]
Kind = Literal["regular", "irregular", "fixed"]


class Category(BaseModel):
    id: str
    name: str
    color: str


DEFAULT_CATEGORIES = [
    Category(id="groceries", name="Продукты", color="#4caf50"),
    Category(id="restaurants", name="Рестораны", color="#ff7043"),
    Category(id="coffee", name="Кофе", color="#8d6e63"),
    Category(id="food_delivery", name="Доставка еды", color="#ffa726"),
    Category(id="taxi", name="Такси", color="#fdd835"),
    Category(id="transport", name="Транспорт", color="#42a5f5"),
    Category(id="health", name="Здоровье", color="#ef5350"),
    Category(id="clothes", name="Одежда", color="#ab47bc"),
    Category(id="home", name="Дом", color="#26a69a"),
    Category(id="entertainment", name="Развлечения", color="#ec407a"),
    Category(id="subscriptions", name="Подписки", color="#7e57c2"),
    Category(id="phone_internet", name="Связь", color="#5c6bc0"),
    Category(id="housing", name="Жильё", color="#78909c"),
    Category(id="travel", name="Путешествия", color="#29b6f6"),
    Category(id="gifts", name="Подарки", color="#d4e157"),
    Category(id="other", name="Прочее", color="#bdbdbd"),
]


class CategoryRule(BaseModel):
    pattern: str = Field(min_length=1)
    category: str


class Settings(BaseModel):
    base_currency: Currency = "EUR"
    input_currency: Currency = "RSD"
    categories: list[Category] = DEFAULT_CATEGORIES
    category_rules: list[CategoryRule] = []
    # Коэффициент к официальному курсу НБС: реальный курс обмена = курс НБС × коэффициент
    rate_adjustments: dict[Currency, float] = {}


class Money(BaseModel):
    amount: float
    currency: Currency


class FixedTemplate(BaseModel):
    id: str
    name: str = Field(min_length=1)
    amount: float
    currency: Currency
    category: str | None = None
    since: str = Field(pattern=r"^\d{4}-\d{2}$", description="Первый месяц действия, YYYY-MM")


class ExpenseInput(BaseModel):
    """Трата в том виде, в каком её вводит пользователь или агент."""

    date: Date
    time: Time | None = None
    name: str = Field(min_length=1, description="Название траты или организация со скриншота")
    amount: float = Field(description="Сумма в исходной валюте; отрицательная — возврат")
    currency: Currency | None = Field(None, description="Пусто — валюта ввода по умолчанию")
    category: str | None = Field(None, description="id категории; пусто — подбор по правилам")
    kind: Literal["regular", "irregular"] = "regular"
    over_budget: bool = Field(False, description="Только для irregular: трата сверх бюджета")
    note: str = ""
    source: Literal["chat", "screenshot", "manual"]


class Expense(BaseModel):
    id: str
    date: Date
    time: Time | None = None
    name: str = Field(min_length=1)
    amount: float
    currency: Currency
    category: str | None = None
    kind: Kind = "regular"
    over_budget: bool = False
    note: str = ""
    source: Literal["chat", "screenshot", "manual", "fixed"]
    fixed_id: str | None = None

    @model_validator(mode="after")
    def check(self):
        if self.amount == 0:
            raise ValueError("Сумма не может быть нулевой")
        if self.over_budget and self.kind != "irregular":
            raise ValueError("«Сверх бюджета» можно отметить только у нерегулярной траты")
        return self


class MonthFile(BaseModel):
    fixed_applied: list[str] = []
    expenses: list[Expense] = []
