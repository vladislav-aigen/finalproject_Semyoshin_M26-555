"""JSON-логи с ограничением размера и ротацией файлов."""

import json
import logging
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from valutatrade_hub.infra.settings import SettingsLoader


class JsonFormatter(logging.Formatter):
    """Форматтер записи события без пользовательских паролей."""

    def format(self, record):
        """Сериализовать одну запись лога в JSON."""
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event.update(getattr(record, "event", {}))
        if record.exc_info:
            event["traceback"] = self.formatException(record.exc_info)
        output = json.dumps(event, ensure_ascii=False, default=str)
        for name in ("EXCHANGERATE_API_KEY", "COINGECKO_API_KEY"):
            secret = os.getenv(name)
            if secret:
                output = output.replace(secret, "[REDACTED]")
        output = re.sub(r'(/v6/)[^/\s"?]+(/latest/)', r"\1[REDACTED]\2", output)
        return output


def setup_logging():
    """Подключить отдельные журналы операций и парсера."""
    settings = SettingsLoader()
    folder = Path(settings.get("logs_dir"))
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("actions", "parser"):
        logger = logging.getLogger(f"valutatrade.{name}")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        handler = RotatingFileHandler(
            folder / f"{name}.log",
            maxBytes=settings.get("log_max_bytes"),
            backupCount=settings.get("log_backup_count"),
            encoding="utf-8",
        )
        handler.setFormatter(JsonFormatter())
        handler.setLevel(logging.DEBUG if name == "parser" else logging.INFO)
        logger.addHandler(handler)
        logger.setLevel(
            logging.DEBUG if name == "parser" else settings.get("log_level")
        )
        logger.propagate = False


@contextmanager
def parser_console_logging():
    """Временно показывать INFO/ERROR парсера в консоли команды обновления."""
    logger = logging.getLogger("valutatrade.parser")
    handler = logging.StreamHandler()
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    try:
        yield
    finally:
        logger.removeHandler(handler)
        handler.close()
