"""Регистрация, сессия, сделки и представление портфеля."""

from valutatrade_hub.core.currencies import CryptoCurrency, get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError, ValutaTradeError
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.utils import positive_number
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class WalletService:
    """Сценарии кошелька; текущая сессия живёт только в памяти процесса."""

    def __init__(self):
        self.db = DatabaseManager()
        self.rates = RateService()
        self.current_user = None

    def register(self, username: str, password: str) -> User:
        """Записать пользователя и пустой портфель."""
        if not isinstance(username, str) or not username.strip():
            raise ValueError("Имя не может быть пустым")
        with self.db.lock:
            users = self.db.read("users.json", [])
            if any(row["username"] == username.strip() for row in users):
                raise ValueError(f"Имя пользователя '{username}' уже занято")
            user_id = max((row["user_id"] for row in users), default=0) + 1
            user = User.create(user_id, username, password)
            portfolios = self.db.read("portfolios.json", [])
            old_portfolios = list(portfolios)
            portfolios.append({"user_id": user_id, "wallets": {}})
            self.db.write("portfolios.json", portfolios)
            try:
                self.db.write("users.json", users + [user.to_dict()])
            except Exception:
                self.db.write("portfolios.json", old_portfolios)
                raise
            return user

    def login(self, username: str, password: str) -> User:
        """Проверить пароль и установить текущего пользователя."""
        self.current_user = None
        row = next(
            (u for u in self.db.read("users.json", []) if u["username"] == username),
            None,
        )
        if row is None:
            raise ValueError(f"Пользователь '{username}' не найден")
        user = User(**row)
        if not user.verify_password(password):
            raise ValueError("Неверный пароль")
        self.current_user = user
        return user

    def logout(self):
        """Завершить текущую сессию."""
        self.current_user = None

    def _require_user(self):
        if self.current_user is None:
            raise ValueError("Сначала выполните login")
        return self.current_user

    def _load_portfolio(self):
        user = self._require_user()
        records = self.db.read("portfolios.json", [])
        row = next((r for r in records if r["user_id"] == user.user_id), None)
        if row is None:
            raise ValueError("Портфель пользователя не найден")
        wallets = {
            code: Wallet(code, data["balance"]) for code, data in row["wallets"].items()
        }
        return records, row, Portfolio(user.user_id, wallets, user, self.rates.get_rate)

    @log_action("BUY", verbose=True)
    def buy(self, currency_code: str, amount: float):
        """Увеличить баланс валюты и вернуть оценочную стоимость в USD."""
        return self._trade(currency_code, amount, "BUY")

    @log_action("SELL", verbose=True)
    def sell(self, currency_code: str, amount: float):
        """Уменьшить баланс валюты и вернуть оценочную выручку в USD."""
        return self._trade(currency_code, amount, "SELL")

    def _trade(self, currency_code, amount, action):
        self._require_user()
        get_currency(currency_code)
        amount = positive_number(amount)
        if action == "SELL":
            # Ошибки баланса проверяем до сети; под блокировкой проверим повторно.
            _, _, portfolio = self._load_portfolio()
            wallet = portfolio.get_wallet(currency_code)
            if wallet is None:
                raise ValueError(f"У вас нет кошелька '{currency_code}'")
            if amount > wallet.balance:
                raise InsufficientFundsError(wallet.balance, amount, currency_code)
        rate = self.rates.get_rate(currency_code, "USD")["rate"]
        value = positive_number(amount * rate)
        with self.db.lock:
            records, row, portfolio = self._load_portfolio()
            currency = portfolio.get_wallet(currency_code)
            if action == "SELL" and currency is None:
                raise ValueError(f"У вас нет кошелька '{currency_code}'")
            currency = portfolio.add_currency(currency_code)
            before = {currency_code: currency.balance}
            if action == "BUY":
                currency.deposit(amount)
            else:
                currency.withdraw(amount)
            after = {currency_code: currency.balance}
            result = {
                "action": action,
                "currency": currency_code,
                "amount": amount,
                "rate": rate,
                "value": value,
                "before": before,
                "after": after,
            }
            row.update(portfolio.to_dict())
            self.db.write("portfolios.json", records)
            return result

    def show_portfolio(self, base=None) -> dict:
        """Подготовить балансы и суммарную стоимость для интерфейса."""
        base = base if base is not None else SettingsLoader().get("base_currency")
        get_currency(base)
        _, _, portfolio = self._load_portfolio()
        rows = []
        for code, wallet in sorted(portfolio.wallets.items()):
            rate = self.rates.get_rate(code, base)["rate"] if wallet.balance else 0
            rows.append((code, wallet.balance, wallet.balance * rate))
        return {
            "username": portfolio.user.username,
            "base": base,
            "rows": rows,
            "total": sum(row[2] for row in rows),
        }

    def show_rates(self, currency=None, top=None, base=None) -> dict:
        """Отобрать курсы и вернуть строки таблицы с диагностикой."""
        base = base if base is not None else SettingsLoader().get("base_currency")
        get_currency(base)
        if currency:
            get_currency(currency)
        if top is not None and top <= 0:
            raise ValueError("--top должен быть положительным целым числом")
        snapshot = self.db.read("rates.json", {})
        if not snapshot.get("pairs"):
            return {"rows": [], "errors": [], "empty_cache": True}
        codes = sorted({pair.split("_")[0] for pair in snapshot["pairs"]})
        if currency:
            codes = [currency]
        if top is not None:
            codes = [c for c in codes if isinstance(get_currency(c), CryptoCurrency)]
        rows, errors = [], []
        # Просмотр снимка не вызывает скрытый сетевой запрос для каждой строки.
        cache_rates = RateService(auto_refresh=False)
        for code in codes:
            try:
                rate = cache_rates.get_rate(code, base)
                rows.append((code, rate["rate"], rate["updated_at"], rate["source"]))
            except ValutaTradeError as error:
                errors.append(f"{code}: {error}")
        if top is not None:
            rows = sorted(rows, key=lambda row: row[1], reverse=True)[:top]
        return {"rows": rows, "errors": errors, "empty_cache": False}
