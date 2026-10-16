"""Пользователь, валютный кошелёк и портфель."""

import hashlib
import hmac
import math
import secrets
from datetime import UTC, datetime

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError
from valutatrade_hub.core.utils import positive_number


class User:
    """Пользователь с солью и односторонним хешем пароля."""

    def __init__(self, user_id, username, hashed_password, salt, registration_date):
        self._user_id = user_id
        self.username = username
        self._hashed_password = hashed_password
        self._salt = salt
        self._registration_date = (
            datetime.fromisoformat(registration_date)
            if isinstance(registration_date, str)
            else registration_date
        )

    @classmethod
    def create(cls, user_id: int, username: str, password: str):
        """Создать пользователя с новой криптографически случайной солью."""
        user = cls(user_id, username, "", "", datetime.now(UTC))
        user.change_password(password)
        return user

    @property
    def user_id(self):
        """Неизменяемый идентификатор."""
        return self._user_id

    @property
    def username(self):
        """Имя пользователя."""
        return self._username

    @username.setter
    def username(self, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self):
        """Хеш для сериализации."""
        return self._hashed_password

    @property
    def salt(self):
        """Индивидуальная соль."""
        return self._salt

    @property
    def registration_date(self):
        """Дата регистрации."""
        return self._registration_date

    def get_user_info(self) -> dict:
        """Вернуть сведения без пароля, хеша и соли."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": self.registration_date.isoformat(),
        }

    def change_password(self, new_password: str):
        """Заменить пароль и соль с проверкой минимальной длины."""
        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValueError("Пароль должен быть не короче 4 символов")
        self._salt = secrets.token_hex(16)
        self._hashed_password = self._hash(new_password)

    def _hash(self, password):
        return hashlib.sha256((password + self.salt).encode()).hexdigest()

    def verify_password(self, password: str) -> bool:
        """Сравнить хеши с постоянным временем сравнения."""
        return hmac.compare_digest(self._hash(password), self.hashed_password)

    def to_dict(self) -> dict:
        """Сериализовать пользователя для users.json."""
        return self.get_user_info() | {
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }


class Wallet:
    """Баланс одной валюты с контролем входящих и исходящих сумм."""

    def __init__(self, currency_code: str, balance: float = 0.0):
        self.currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def balance(self) -> float:
        """Текущий остаток."""
        return self._balance

    @balance.setter
    def balance(self, value):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("Баланс должен быть конечным неотрицательным числом")
        self._balance = float(value)

    def deposit(self, amount: float):
        """Зачислить положительную сумму."""
        self.balance += positive_number(amount)

    def withdraw(self, amount: float):
        """Списать сумму, если средств достаточно."""
        amount = positive_number(amount)
        if amount > self.balance:
            raise InsufficientFundsError(self.balance, amount, self.currency_code)
        self.balance -= amount

    def get_balance_info(self) -> str:
        """Отформатировать остаток и код валюты."""
        return f"{self.balance:.4f} {self.currency_code}"


class Portfolio:
    """Кошельки одного пользователя и оценка стоимости портфеля."""

    def __init__(self, user_id: int, wallets=None, user=None, rate_provider=None):
        self._user_id = user_id
        self._user = user
        self._wallets = dict(wallets or {})
        self._rate_provider = rate_provider

    @property
    def user(self):
        """Пользователь портфеля, только для чтения."""
        return self._user

    @property
    def wallets(self):
        """Копия словаря кошельков."""
        return self._wallets.copy()

    def add_currency(self, currency_code: str):
        """Создать отсутствующий кошелёк, сохраняя существующий баланс."""
        get_currency(currency_code)
        if currency_code not in self._wallets:
            self._wallets[currency_code] = Wallet(currency_code)
        return self._wallets[currency_code]

    def get_wallet(self, currency_code: str):
        """Найти кошелёк по коду валюты."""
        return self._wallets.get(currency_code)

    def get_total_value(self, base_currency="USD") -> float:
        """Сложить стоимость кошельков по заданному поставщику курсов."""
        get_currency(base_currency)
        if self._rate_provider is None:
            from valutatrade_hub.core.rates import RateService

            self._rate_provider = RateService().get_rate
        return sum(
            wallet.balance * self._rate_provider(code, base_currency)["rate"]
            for code, wallet in self._wallets.items()
            if wallet.balance
        )

    def to_dict(self):
        """Подготовить JSON-представление портфеля."""
        return {
            "user_id": self._user_id,
            "wallets": {
                code: {"balance": wallet.balance}
                for code, wallet in self._wallets.items()
            },
        }
