"""Загрузка конфигурации приложения из TOML и переменных окружения."""

import os
import tomllib
from pathlib import Path

from valutatrade_hub.core.currencies import get_currency


class SettingsLoader:
    """Единственный экземпляр настроек; __new__ выбран за простоту."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            instance = super().__new__(cls)
            instance.reload()
            cls._instance = instance
        return cls._instance

    def reload(self):
        """Повторно прочитать настройки из текущего окружения."""
        path = Path(os.getenv("VALUTATRADE_CONFIG", "pyproject.toml"))
        config = {}
        if path.is_file():
            with path.open("rb") as stream:
                config = tomllib.load(stream).get("tool", {}).get("valutatrade", {})
        values = {
            "data_dir": os.getenv(
                "VALUTATRADE_DATA_DIR", config.get("data_dir", "data")
            ),
            "logs_dir": os.getenv(
                "VALUTATRADE_LOG_DIR", config.get("logs_dir", "logs")
            ),
            "rates_ttl_seconds": int(
                os.getenv("VALUTATRADE_RATES_TTL", config.get("rates_ttl_seconds", 300))
            ),
            "base_currency": config.get("base_currency", "USD"),
            "snapshot_cache_seconds": int(config.get("snapshot_cache_seconds", 30)),
            "max_clock_skew_seconds": int(config.get("max_clock_skew_seconds", 60)),
            "log_format": "json",
            "log_level": config.get("log_level", "INFO"),
            "log_max_bytes": 1_048_576,
            "log_backup_count": 3,
        }
        if values["rates_ttl_seconds"] <= 0 or values["snapshot_cache_seconds"] <= 0:
            raise ValueError("TTL должен быть положительным")
        if values["max_clock_skew_seconds"] < 0:
            raise ValueError("Допуск часов не может быть отрицательным")
        get_currency(values["base_currency"])
        self._values = values

    def get(self, key: str, default=None):
        """Вернуть значение настройки или значение по умолчанию."""
        return self._values.get(key, default)
