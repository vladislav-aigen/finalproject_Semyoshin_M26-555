"""Проверка структуры JSON до обращения к полям сохранённых записей."""

import math

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.utils import parse_timestamp, positive_number


def _require(condition):
    if not condition:
        raise ValueError("Неверная структура записи")


def _text(value):
    _require(isinstance(value, str) and bool(value.strip()))


def _unique_ids(rows):
    seen = set()
    for row in rows:
        _require(isinstance(row, dict))
        identifier = row["user_id"]
        _require(type(identifier) is int and identifier > 0 and identifier not in seen)
        seen.add(identifier)


def validate_rate_record(pair, record):
    """Проверить пару, положительный курс, дату и необязательный источник."""
    _require(isinstance(pair, str) and isinstance(record, dict))
    left, right = pair.split("_")
    get_currency(left)
    get_currency(right)
    positive_number(record["rate"], "rate")
    parse_timestamp(record["updated_at"])
    if "source" in record:
        _text(record["source"])


def validate_document(name, data):
    """Проверить известный формат; служебные JSON оставить универсальными."""
    if name in ("users.json", "portfolios.json"):
        _require(isinstance(data, list))
        _unique_ids(data)
    if name == "users.json":
        usernames = set()
        fields = {"user_id", "username", "hashed_password", "salt", "registration_date"}
        for row in data:
            _require(set(row) == fields)
            for field in ("username", "hashed_password", "salt"):
                _text(row[field])
            _require(row["username"] not in usernames)
            usernames.add(row["username"])
            parse_timestamp(row["registration_date"])
    elif name == "portfolios.json":
        for row in data:
            wallets = row["wallets"]
            _require(isinstance(wallets, dict))
            for code, wallet in wallets.items():
                get_currency(code)
                _require(isinstance(wallet, dict))
                balance = wallet["balance"]
                _require(type(balance) in (int, float))
                _require(math.isfinite(balance) and balance >= 0)
    elif name == "rates.json":
        _require(isinstance(data, dict))
        pairs = data.get("pairs", {})
        _require(isinstance(pairs, dict))
        for pair, record in pairs.items():
            validate_rate_record(pair, record)
        if data.get("last_refresh") is not None:
            parse_timestamp(data["last_refresh"])
    elif name == "exchange_rates.json":
        _require(isinstance(data, list))
        for row in data:
            _require(isinstance(row, dict))
            _text(row["id"])
            validate_rate_record(
                f"{row['from_currency']}_{row['to_currency']}",
                {
                    "rate": row["rate"],
                    "updated_at": row["timestamp"],
                    "source": row["source"],
                },
            )
