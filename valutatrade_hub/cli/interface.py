"""Разбор пользовательских команд; расчёты выполняются в Core Service."""

import argparse
import shlex
import sys
from getpass import getpass

from prettytable import PrettyTable

from valutatrade_hub import __version__
from valutatrade_hub.core.currencies import CURRENCIES
from valutatrade_hub.core.exceptions import CurrencyNotFoundError, ValutaTradeError
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.decorators import confirm_action
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import parser_console_logging, setup_logging
from valutatrade_hub.parser_service.updater import make_updater


class CommandParser(argparse.ArgumentParser):
    """Парсер без завершения REPL при ошибке в аргументах."""

    def error(self, message):
        """Передать ошибку ввода интерфейсу."""
        raise ValueError(message)


def make_parser() -> CommandParser:
    """Описать команды и их аргументы."""
    base = SettingsLoader().get("base_currency")
    parser = CommandParser(prog="valutatrade", description="ValutaTrade Hub")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command")
    for command in ("register", "login"):
        sub = commands.add_parser(command)
        sub.add_argument("--username", required=True)
        sub.add_argument("--password", help="Если не указан, запрашивается скрыто")
    sub = commands.add_parser("show-portfolio")
    sub.add_argument("--base", default=base)
    for command in ("buy", "sell"):
        sub = commands.add_parser(command)
        sub.add_argument("--currency", required=True)
        sub.add_argument("--amount", required=True, type=float)
        sub.add_argument("--confirm", action="store_true")
    sub = commands.add_parser("get-rate")
    sub.add_argument("--from", dest="from_code", required=True)
    sub.add_argument("--to", dest="to_code", required=True)
    sub = commands.add_parser("update-rates")
    sub.add_argument("--source", choices=["coingecko", "exchangerate"])
    sub.add_argument("--demo", action="store_true", help="Явно включить учебные курсы")
    sub = commands.add_parser("show-rates")
    sub.add_argument("--currency")
    sub.add_argument("--top", type=int)
    sub.add_argument("--base", default=base)
    for command in ("logout", "currencies", "help", "exit", "quit"):
        commands.add_parser(command)
    return parser


class CommandInterface:
    """Одна интерактивная сессия кошелька."""

    def __init__(self):
        self.service = WalletService()
        self.parser = make_parser()

    def execute(self, line: str) -> bool:
        """Выполнить команду; вернуть False при запросе выхода."""
        try:
            arguments = shlex.split(line)
            if not arguments:
                return True
            args = self.parser.parse_args(arguments)
            return self.dispatch(args)
        except SystemExit:
            return True
        except CurrencyNotFoundError as error:
            print(f"{error}. Доступные валюты: {', '.join(CURRENCIES)}")
        except (ValutaTradeError, ValueError, OSError) as error:
            print(f"Ошибка: {error}")
        return True

    def dispatch(self, args) -> bool:
        """Выбрать сценарий и отформатировать его результат."""
        service, command = self.service, args.command
        if command in ("exit", "quit"):
            return False
        if command in ("help", None):
            self.parser.print_help()
        elif command == "register":
            user = service.register(args.username, self._password(args))
            print(
                f"Пользователь '{user.username}' зарегистрирован (id={user.user_id}). "
                "Войдите командой login."
            )
        elif command == "login":
            user = service.login(args.username, self._password(args))
            print(f"Вы вошли как '{user.username}'")
        elif command == "logout":
            service.logout()
            print("Сессия завершена")
        elif command in ("buy", "sell"):
            action = self._confirmed_trade if args.confirm else self._trade
            action(command, args.currency, args.amount)
        elif command == "show-portfolio":
            result = service.show_portfolio(args.base)
            print(f"Портфель пользователя '{result['username']}' (база: {args.base}):")
            if not result["rows"]:
                print("Портфель пуст. Купите валюту командой buy.")
            else:
                table = PrettyTable(["Валюта", "Баланс", f"Стоимость, {args.base}"])
                for code, balance, value in result["rows"]:
                    table.add_row([code, f"{balance:.8f}", f"{value:.2f}"])
                print(table)
                print(f"ИТОГО: {result['total']:,.2f} {args.base}")
        elif command == "get-rate":
            rate = service.rates.get_rate(args.from_code, args.to_code)
            print(
                f"Курс {args.from_code}→{args.to_code}: {rate['rate']:.8f} "
                f"(обновлено: {rate['updated_at']}, источник: {rate['source']})"
            )
            print(f"Обратный курс: {1 / rate['rate']:.8f}")
        elif command == "update-rates":
            with parser_console_logging():
                result = make_updater(args.source, args.demo).run_update()
            print(
                f"Обновлено курсов: {result['updated']}. "
                f"Последнее обновление: {result['last_refresh']}"
            )
            if args.demo:
                print("ДЕМО: использованы синтетические учебные курсы.")
            if result["errors"]:
                print("Обновление завершено с ошибками. Подробности: logs/parser.log")
            else:
                print("Обновление завершено успешно.")
            for error in result["errors"]:
                print(f"Источник не обновлён: {error}")
        elif command == "show-rates":
            self._show_rates(args)
        elif command == "currencies":
            for currency in CURRENCIES.values():
                print(currency.get_display_info())
        return True

    @staticmethod
    def _password(args):
        return args.password if args.password is not None else getpass("Пароль: ")

    def _trade(self, action, currency, amount):
        result = getattr(self.service, action)(currency, amount)
        label = "Покупка" if action == "buy" else "Продажа"
        print(
            f"{label} выполнена: {amount:.4f} {currency} "
            f"по курсу {result['rate']:.4f} USD/{currency}"
        )
        for code, balance in result["after"].items():
            print(f"- {code}: было {result['before'][code]:.4f} → стало {balance:.4f}")
        print(f"Оценочная стоимость в USD: {result['value']:.2f} USD")

    @confirm_action("сделку")
    def _confirmed_trade(self, action, currency, amount):
        return self._trade(action, currency, amount)

    def _show_rates(self, args):
        result = self.service.show_rates(args.currency, args.top, args.base)
        if result["empty_cache"]:
            print("Локальный кеш курсов пуст. Выполните 'update-rates'.")
            return
        for error in result["errors"]:
            print(error)
        table = PrettyTable(["Пара", "Курс", "Обновлено (UTC)", "Источник"])
        for code, value, timestamp, source in result["rows"]:
            table.add_row([f"{code}_{args.base}", f"{value:.8f}", timestamp, source])
        print(table)

    def run(self):
        """Читать команды до exit, EOF или прерывания пользователем."""
        print("ValutaTrade Hub. Команды: help; выход: exit.")
        while True:
            try:
                if not self.execute(input("> ")):
                    break
            except (EOFError, KeyboardInterrupt):
                print("\nДо свидания!")
                break


def main():
    """Запустить REPL или отдельную несессионную команду."""
    try:
        setup_logging()
        interface = CommandInterface()
        if len(sys.argv) > 1:
            interface.dispatch(interface.parser.parse_args())
        else:
            interface.run()
    except (ValutaTradeError, ValueError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1) from None
