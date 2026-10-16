"""Клиенты источников с единым контрактом «пара → курс»."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import positive_number, utc_now
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Базовый клиент: результат всегда содержит курсы к USD."""

    source = "unknown"

    def __init__(self, config=None):
        self.config = config or ParserConfig()
        self.updated_at = None

    @abstractmethod
    def fetch_rates(self) -> dict:
        """Получить словарь нормализованных курсов."""

    def _get(self, url, **kwargs):
        logger = logging.getLogger("valutatrade.parser")
        safe_url = url
        if self.config.EXCHANGERATE_API_KEY:
            safe_url = safe_url.replace(self.config.EXCHANGERATE_API_KEY, "[REDACTED]")
        started = time.monotonic()
        logger.debug("GET %s", safe_url)
        try:
            response = requests.get(url, timeout=self.config.REQUEST_TIMEOUT, **kwargs)
            logger.debug(
                "%s: status=%s, elapsed_ms=%.1f",
                self.source,
                response.status_code,
                (time.monotonic() - started) * 1000,
            )
            if response.status_code == 429:
                raise ApiRequestError(f"{self.source}: превышен лимит запросов (429)")
            if response.status_code in (401, 403):
                raise ApiRequestError(f"{self.source}: проверьте API-ключ")
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Ожидается JSON-объект")
            return data
        except (requests.RequestException, ValueError) as error:
            # URL ExchangeRate-API содержит ключ; текст сетевой ошибки не выводим.
            raise ApiRequestError(
                f"{self.source}: ошибка сети или некорректный ответ"
            ) from error


class CoinGeckoClient(BaseApiClient):
    """Получение долларовых котировок криптовалют CoinGecko."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict:
        config = self.config
        headers = {}
        if config.COINGECKO_API_KEY:
            headers["x-cg-demo-api-key"] = config.COINGECKO_API_KEY
        data = self._get(
            config.COINGECKO_URL,
            params={
                "ids": ",".join(
                    config.CRYPTO_ID_MAP[c] for c in config.CRYPTO_CURRENCIES
                ),
                "vs_currencies": "usd",
                "include_last_updated_at": "true",
            },
            headers=headers,
        )
        try:
            result = {
                f"{code}_USD": positive_number(
                    data[config.CRYPTO_ID_MAP[code]]["usd"], "rate"
                )
                for code in config.CRYPTO_CURRENCIES
            }
            timestamps = [
                data[config.CRYPTO_ID_MAP[c]].get("last_updated_at")
                for c in config.CRYPTO_CURRENCIES
            ]
            valid = [value for value in timestamps if value is not None]
            self.updated_at = (
                datetime.fromtimestamp(min(valid), UTC).isoformat()
                if valid
                else utc_now()
            )
            return result
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ApiRequestError(
                "CoinGecko: отсутствуют корректные котировки"
            ) from error


class ExchangeRateApiClient(BaseApiClient):
    """Получение фиатных котировок с инверсией USD→валюта."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict:
        config = self.config
        if not config.EXCHANGERATE_API_KEY:
            raise ApiRequestError("Задайте переменную EXCHANGERATE_API_KEY")
        data = self._get(
            f"{config.EXCHANGERATE_API_URL}/{config.EXCHANGERATE_API_KEY}"
            f"/latest/{config.BASE_CURRENCY}"
        )
        if data.get("result") != "success":
            raise ApiRequestError("ExchangeRate-API: проверьте ключ и лимит запросов")
        try:
            if data.get("base_code") != config.BASE_CURRENCY:
                raise ValueError("Неожиданная базовая валюта")
            rates = data.get("conversion_rates", data.get("rates", {}))
            usd = positive_number(
                rates.get("USD", 1) if config.BASE_CURRENCY == "USD" else rates["USD"],
                "rate",
            )
            result = {
                f"{code}_USD": usd / positive_number(rates[code], "rate")
                for code in config.FIAT_CURRENCIES
            }
            timestamp = data.get("time_last_update_unix")
            self.updated_at = (
                datetime.fromtimestamp(timestamp, UTC).isoformat()
                if timestamp is not None
                else utc_now()
            )
            return result
        except (KeyError, TypeError, ValueError, OverflowError) as error:
            raise ApiRequestError("ExchangeRate-API: некорректные котировки") from error


class DemoClient(BaseApiClient):
    """Явно включаемый офлайн-источник учебных, не рыночных курсов."""

    source = "Demo (synthetic)"

    def fetch_rates(self) -> dict:
        """Вернуть постоянные значения для воспроизводимой демонстрации."""
        self.updated_at = utc_now()
        return {
            "BTC_USD": 60000.0,
            "ETH_USD": 3000.0,
            "SOL_USD": 150.0,
            "EUR_USD": 1.1,
            "GBP_USD": 1.3,
            "RUB_USD": 0.01,
        }
