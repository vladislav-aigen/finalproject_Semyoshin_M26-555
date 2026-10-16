"""Параметры источников курсов и сетевых запросов."""

import os
from dataclasses import dataclass, field

from valutatrade_hub.infra.database import DatabaseManager


@dataclass
class ParserConfig:
    """Конфигурация API; секреты читаются только из окружения."""

    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", ""), repr=False
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", ""), repr=False
    )
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict = field(
        default_factory=lambda: {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana"}
    )
    REQUEST_TIMEOUT: int = 10
    UPDATE_INTERVAL: int = 300

    @property
    def RATES_FILE_PATH(self):
        """Путь к снимку актуальных курсов."""
        return DatabaseManager().path("rates.json")

    @property
    def HISTORY_FILE_PATH(self):
        """Путь к истории курсов."""
        return DatabaseManager().path("exchange_rates.json")
