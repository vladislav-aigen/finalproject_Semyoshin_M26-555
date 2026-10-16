"""Валидация чисел, даты и кэширование результатов через замыкание."""

import math
import time
from datetime import UTC, datetime


def positive_number(value: float, name: str = "amount") -> float:
    """Принять только конечное положительное число, исключая bool."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"'{name}' должен быть положительным числом")
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"'{name}' должен быть положительным числом")
    return value


def utc_now() -> str:
    """Вернуть текущий момент в ISO 8601 UTC."""
    return datetime.now(UTC).isoformat(timespec="microseconds")


def parse_timestamp(value: str) -> datetime:
    """Разобрать ISO-дату; старые даты без часового пояса считать UTC."""
    if not isinstance(value, str):
        raise ValueError("Дата должна быть строкой ISO 8601")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result


def create_cacher(ttl_seconds: float = 60):
    """Создать ограниченный по времени кэш в замыкании."""
    cache = {}

    def cache_result(key, value_func):
        now = time.monotonic()
        for expired in [k for k, (_, end) in cache.items() if end <= now]:
            del cache[expired]
        if key not in cache:
            cache[key] = (value_func(), now + ttl_seconds)
        return cache[key][0]

    return cache_result
