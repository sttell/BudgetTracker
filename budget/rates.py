import logging
import time
from datetime import date as Date

import httpx

from budget.storage import Storage

log = logging.getLogger(__name__)

# Зеркало курсового листа Народного банка Сербии; на выходные отдаёт лист последнего рабочего дня.
NBS_URL = "https://kurs.resenje.org/api/v1/currencies/{code}/rates/{day}"
RETRY_AFTER_FAILURE_SEC = 5 * 60


class RateUnavailable(Exception):
    pass


def fetch_nbs(code: str, day: Date) -> float:
    """Официальный средний курс НБС: RSD за 1 единицу валюты."""
    resp = httpx.get(NBS_URL.format(code=code.lower(), day=day.isoformat()), timeout=5)
    resp.raise_for_status()
    return float(resp.json()["exchange_middle"])


class Rates:
    def __init__(self, storage: Storage, fetch=fetch_nbs, adjustments=dict):
        self.storage = storage
        self.fetch = fetch
        self.adjustments = adjustments  # () -> {валюта: коэффициент к курсу НБС}
        self._failed_at = None

    def rsd_per(self, currency: str, day: Date) -> float:
        if currency == "RSD":
            return 1.0
        cache = self.storage.read("rates.json", {})
        key = day.isoformat()
        if currency in cache.get(key, {}):
            return cache[key][currency]
        if day <= Date.today() and self._can_fetch():
            try:
                value = self.fetch(currency, day)
            except Exception as e:
                log.warning("Курс %s на %s не получен: %s", currency, key, e)
                self._failed_at = time.monotonic()
            else:
                self.set_rate(day, currency, value)
                return value
        return self._nearest(cache, currency, key)

    def effective(self, currency: str, day: Date) -> float:
        """Реальный курс обмена: курс НБС × коэффициент валюты."""
        return self.rsd_per(currency, day) * self.adjustments().get(currency, 1.0)

    def convert(self, amount: float, from_cur: str, to_cur: str, day: Date) -> float:
        if from_cur == to_cur:
            return amount
        return amount * self.effective(from_cur, day) / self.effective(to_cur, day)

    def set_rate(self, day: Date, currency: str, rsd_per_unit: float) -> None:
        with self.storage.lock():
            cache = self.storage.read("rates.json", {})
            cache.setdefault(day.isoformat(), {})[currency] = rsd_per_unit
            self.storage.write("rates.json", dict(sorted(cache.items())))

    def _can_fetch(self) -> bool:
        return self._failed_at is None or time.monotonic() - self._failed_at > RETRY_AFTER_FAILURE_SEC

    @staticmethod
    def _nearest(cache: dict, currency: str, key: str) -> float:
        known = sorted(k for k, v in cache.items() if currency in v)
        earlier = [k for k in known if k <= key]
        later = [k for k in known if k > key]
        if earlier:
            return cache[earlier[-1]][currency]
        if later:
            return cache[later[0]][currency]
        raise RateUnavailable(f"Нет курса {currency} на {key}: источник недоступен, задайте курс вручную")
