"""Чтение актуальных прямых, обратных и кросс-курсов."""

from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import (
    create_cacher,
    parse_timestamp,
    positive_number,
    utc_now,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class RateService:
    """Поставщик курсов из снимка Parser Service с проверкой TTL."""

    def __init__(self, auto_refresh=True):
        self.auto_refresh = auto_refresh
        self.db = DatabaseManager()
        self._cache = create_cacher(30)

    def get_rate(self, from_code: str, to_code: str) -> dict:
        """При отсутствии свежего курса один раз обновить его через парсер."""
        get_currency(from_code)
        get_currency(to_code)
        try:
            return self._from_cache(from_code, to_code)
        except ApiRequestError:
            if not self.auto_refresh:
                raise
        from valutatrade_hub.parser_service.updater import make_updater

        try:
            make_updater().run_update()
            self._cache = create_cacher(30)
            return self._from_cache(from_code, to_code)
        except ApiRequestError as error:
            raise ApiRequestError(
                f"Курс {from_code}→{to_code} недоступен после обновления. "
                "Повторите позже или выполните update-rates. " + str(error)
            ) from error

    def _from_cache(self, from_code: str, to_code: str) -> dict:
        """Найти курс и отклонить просроченные или повреждённые значения."""
        get_currency(from_code)
        get_currency(to_code)
        if from_code == to_code:
            return {"rate": 1.0, "updated_at": utc_now(), "source": "Identity"}
        path = self.db.path("rates.json")
        key = (path, path.stat().st_mtime_ns if path.exists() else None)
        snapshot = self._cache(key, lambda: self.db.read("rates.json", {}))
        pairs = snapshot.get("pairs", snapshot)
        now = datetime.now(UTC)
        ttl = SettingsLoader().get("rates_ttl_seconds")

        def direct(left, right):
            if left == right:
                return {"rate": 1.0, "updated_at": utc_now(), "source": "Identity"}
            inverse = f"{left}_{right}" not in pairs
            pair = f"{right}_{left}" if inverse else f"{left}_{right}"
            record = pairs.get(pair)
            if not record:
                return None
            try:
                value = positive_number(record["rate"], "rate")
                timestamp = parse_timestamp(record["updated_at"])
                age = (now - timestamp).total_seconds()
                if age < -60 or age > ttl:
                    raise ApiRequestError(
                        f"Курс {pair} устарел или имеет неверную дату. "
                        "Выполните update-rates"
                    )
                return {
                    "rate": 1 / value if inverse else value,
                    "updated_at": record["updated_at"],
                    "source": record.get("source", "cache"),
                }
            except (KeyError, ValueError, TypeError, AttributeError) as error:
                raise ApiRequestError(f"Некорректный курс {pair}") from error

        result = direct(from_code, to_code)
        if result is None:
            left, right = direct(from_code, "USD"), direct(to_code, "USD")
            if left and right:
                result = {
                    "rate": left["rate"] / right["rate"],
                    "updated_at": min(
                        [left["updated_at"], right["updated_at"]], key=parse_timestamp
                    ),
                    "source": f"{left['source']} / {right['source']}",
                }
        if result is None:
            raise ApiRequestError(
                f"Курс {from_code}→{to_code} недоступен. Выполните update-rates"
            )
        positive_number(result["rate"], "rate")
        return result
