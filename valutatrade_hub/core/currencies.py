"""Иерархия и реестр поддерживаемых валют."""

import re
from abc import ABC, abstractmethod

from valutatrade_hub.core.exceptions import CurrencyNotFoundError


def validate_code(code: str) -> str:
    """Проверить формат тикера, состоящего из 2–5 заглавных букв."""
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z]{2,5}", code):
        raise ValueError("Код валюты: 2–5 заглавных латинских букв")
    return code


class Currency(ABC):
    """Общий интерфейс фиатных валют и криптовалют."""

    def __init__(self, name: str, code: str):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Название валюты не может быть пустым")
        self.name = name.strip()
        self.code = validate_code(code)

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть описание валюты для пользовательского интерфейса."""


class FiatCurrency(Currency):
    """Фиатная валюта с указанием страны или зоны эмиссии."""

    def __init__(self, name: str, code: str, issuing_country: str):
        super().__init__(name, code)
        self.issuing_country = issuing_country

    def get_display_info(self) -> str:
        """Вернуть тикер, название и эмитента."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


class CryptoCurrency(Currency):
    """Криптовалюта с алгоритмом и справочной капитализацией."""

    def __init__(self, name: str, code: str, algorithm: str, market_cap: float):
        super().__init__(name, code)
        self.algorithm = algorithm
        self.market_cap = market_cap

    def get_display_info(self) -> str:
        """Вернуть тикер, алгоритм и справочную капитализацию."""
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {self.market_cap:.2e})"
        )


CURRENCIES = {
    "USD": FiatCurrency("US Dollar", "USD", "United States"),
    "EUR": FiatCurrency("Euro", "EUR", "Eurozone"),
    "GBP": FiatCurrency("Pound Sterling", "GBP", "United Kingdom"),
    "RUB": FiatCurrency("Russian Ruble", "RUB", "Russia"),
    "BTC": CryptoCurrency("Bitcoin", "BTC", "SHA-256", 0.0),
    "ETH": CryptoCurrency("Ethereum", "ETH", "Proof of Stake", 0.0),
    "SOL": CryptoCurrency("Solana", "SOL", "Proof of History", 0.0),
}


def get_currency(code: str) -> Currency:
    """Получить зарегистрированную валюту по её коду."""
    validate_code(code)
    if code not in CURRENCIES:
        raise CurrencyNotFoundError(code)
    return CURRENCIES[code]
