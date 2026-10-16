"""Координация клиентов и отказоустойчивое обновление курсов."""

import logging
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import ApiRequestError, CurrencyNotFoundError
from valutatrade_hub.core.utils import parse_timestamp, positive_number, utc_now
from valutatrade_hub.infra.schema import validate_rate_record
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    DemoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Опрашивает независимые источники и сохраняет успешные результаты."""

    def __init__(self, clients, storage=None):
        self.clients = clients
        self.storage = storage or RatesStorage()

    def run_update(self) -> dict:
        """Продолжить обновление при отказе одного источника."""
        logger = logging.getLogger("valutatrade.parser")
        logger.info("Starting rates update")
        updates, errors = {}, []
        for client in self.clients:
            try:
                rates = client.fetch_rates()
                if not isinstance(rates, dict) or not rates:
                    raise ApiRequestError(f"{client.source}: пустой ответ")
                timestamps = getattr(client, "updated_at_by_pair", {})
                if not isinstance(timestamps, dict):
                    timestamps = {}
                batch = {
                    pair: {
                        "rate": positive_number(rate, "rate"),
                        "updated_at": timestamps.get(pair)
                        or client.updated_at
                        or utc_now(),
                        "source": client.source,
                    }
                    for pair, rate in rates.items()
                }
                # Сначала проверяем весь ответ, чтобы плохой источник не успел
                # заменить корректные данные уже опрошенных клиентов.
                for pair, record in batch.items():
                    validate_rate_record(pair, record)
                    ahead = (
                        parse_timestamp(record["updated_at"]) - datetime.now(UTC)
                    ).total_seconds()
                    if ahead > SettingsLoader().get("max_clock_skew_seconds"):
                        raise ValueError("Дата котировки находится в будущем")
                for pair, record in batch.items():
                    if pair not in updates or parse_timestamp(
                        record["updated_at"]
                    ) > parse_timestamp(updates[pair]["updated_at"]):
                        updates[pair] = record
                logger.info("%s: OK (%s rates)", client.source, len(batch))
            except (
                ApiRequestError,
                CurrencyNotFoundError,
                ValueError,
                TypeError,
                KeyError,
                OverflowError,
            ) as error:
                message = f"{client.source}: {error}"
                errors.append(message)
                logger.error("%s", message)
                logger.debug("Source failure: %s", client.source, exc_info=True)
        if not updates:
            logger.error("Update failed: no rates received")
            raise ApiRequestError(
                "Ни один источник не вернул курсы. " + "; ".join(errors)
            )
        logger.info("Writing rates snapshot and history")
        count = self.storage.save(updates)
        result = {
            "updated": count,
            "errors": errors,
            "completed_at": utc_now(),
            "last_refresh": self.storage.last_refresh,
        }
        logger.info("Update completed: %s", result)
        return result


def make_updater(source=None, demo=False) -> RatesUpdater:
    """Собрать набор клиентов для выбранного источника."""
    if demo:
        if source:
            raise ValueError("--demo нельзя совмещать с --source")
        return RatesUpdater([DemoClient()])
    clients = {"coingecko": CoinGeckoClient, "exchangerate": ExchangeRateApiClient}
    return RatesUpdater(
        [clients[source]()] if source else [c() for c in clients.values()]
    )
