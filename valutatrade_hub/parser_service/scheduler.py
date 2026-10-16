"""Периодическое обновление курсов без стороннего планировщика."""

import argparse
import logging
import time

from valutatrade_hub.core.exceptions import ValutaTradeError
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import make_updater


def main():
    """Запустить цикл обновления либо один проход с параметром --once."""
    parser = argparse.ArgumentParser(description="Планировщик курсов ValutaTrade Hub")
    parser.add_argument("--interval", type=int, default=ParserConfig().UPDATE_INTERVAL)
    parser.add_argument("--source", choices=["coingecko", "exchangerate"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval должен быть положительным")
    if args.demo and args.source:
        parser.error("--demo нельзя совмещать с --source")
    setup_logging()
    updater = make_updater(args.source, args.demo)
    try:
        while True:
            try:
                result = updater.run_update()
                print(f"Обновлено курсов: {result['updated']}")
            except (ValutaTradeError, OSError) as error:
                logging.getLogger("valutatrade.parser").error("%s", error)
                if args.once:
                    raise SystemExit(str(error)) from None
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Планировщик остановлен")


if __name__ == "__main__":
    main()
