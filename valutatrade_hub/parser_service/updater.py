"""Координация клиентов и отказоустойчивое обновление курсов."""

import logging

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import positive_number, utc_now
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
                if not rates:
                    raise ApiRequestError(f"{client.source}: пустой ответ")
                batch = {
                    pair: {
                        "rate": positive_number(rate, "rate"),
                        "updated_at": client.updated_at or utc_now(),
                        "source": client.source,
                    }
                    for pair, rate in rates.items()
                }
                updates.update(batch)
                logger.info("%s: OK (%s rates)", client.source, len(batch))
            except (ApiRequestError, ValueError) as error:
                errors.append(str(error))
                logger.error("%s", error)
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
