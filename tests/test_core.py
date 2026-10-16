"""Проверки моделей, денежных инвариантов и срока актуальности курсов."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    StorageError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.core.utils import create_cacher
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.updater import make_updater


@pytest.fixture
def service():
    make_updater(demo=True).run_update()
    service = WalletService()
    service.register("alice", "secret")
    service.login("alice", "secret")
    return service


def test_password_serialization():
    user = User.create(1, "alice", "secret")
    clone = User(**user.to_dict())
    assert clone.verify_password("secret")
    assert not clone.verify_password("wrong")
    assert "hashed_password" not in clone.get_user_info()
    assert "salt" not in clone.get_user_info()
    salt = clone.salt
    clone.change_password("new-password")
    assert clone.salt != salt
    assert clone.verify_password("new-password")
    assert not clone.verify_password("secret")
    with pytest.raises(ValueError):
        clone.username = " "
    with pytest.raises(ValueError):
        clone.change_password("123")


@pytest.mark.parametrize("amount", [0, -1, True, "2", None, float("nan"), float("inf")])
def test_invalid_amount(amount):
    wallet = Wallet("USD", 10)
    with pytest.raises(ValueError):
        wallet.deposit(amount)
    with pytest.raises(ValueError):
        wallet.withdraw(amount)
    assert wallet.balance == 10


def test_wallet_invariants():
    wallet = Wallet("BTC", 1)
    with pytest.raises(InsufficientFundsError):
        wallet.withdraw(2)
    with pytest.raises(ValueError):
        wallet.balance = -1
    assert wallet.balance == 1


def test_portfolio_value_and_copy():
    user = User.create(1, "alice", "secret")
    portfolio = Portfolio(
        1, user=user, rate_provider=lambda a, b: {"rate": 2 if a != b else 1}
    )
    portfolio.add_currency("EUR").deposit(10)
    portfolio.add_currency("EUR")
    portfolio.wallets.clear()
    assert portfolio.get_wallet("EUR").balance == 10
    assert portfolio.get_total_value() == 20
    assert portfolio.user is user


def test_buy_sell_without_usd_wallet(service):
    service.buy("BTC", 0.05)
    assert service.show_portfolio()["total"] == pytest.approx(3000)
    assert service.show_portfolio("EUR")["total"] == pytest.approx(3000 / 1.1)
    service.sell("BTC", 0.02)
    row = service.db.read("portfolios.json", [])[0]
    assert row["wallets"]["BTC"]["balance"] == pytest.approx(0.03)
    assert "USD" not in row["wallets"]
    assert "transactions" not in row
    assert service.show_portfolio()["total"] == pytest.approx(1800)


def test_failure_does_not_change_files(service):
    before = service.db.path("portfolios.json").read_bytes()
    with pytest.raises(ValueError):
        service.sell("BTC", 1)
    assert service.db.path("portfolios.json").read_bytes() == before
    with pytest.raises(CurrencyNotFoundError):
        service.buy("ABC", 1)
    assert service.db.path("portfolios.json").read_bytes() == before


def test_failed_sell_keeps_balance(service):
    service.buy("BTC", 0.05)
    before = service.db.path("portfolios.json").read_bytes()
    with pytest.raises(InsufficientFundsError):
        service.sell("BTC", 0.1)
    assert service.db.path("portfolios.json").read_bytes() == before


def test_usd_can_be_bought_and_sold(service):
    service.buy("USD", 100)
    service.sell("USD", 20)
    assert service.show_portfolio()["total"] == 80


def test_session_and_uniqueness(service):
    with pytest.raises(ValueError, match="занято"):
        service.register("alice", "secret")
    with pytest.raises(ValueError, match="Неверный пароль"):
        service.login("alice", "wrong")
    with pytest.raises(ValueError, match="login"):
        service.buy("BTC", 1)
    service.register("bob", "secret")
    service.login("bob", "secret")
    assert service.show_portfolio()["rows"] == []


def test_direct_inverse_cross_rates(service):
    rates = service.rates
    assert rates.get_rate("BTC", "USD")["rate"] == 60000
    assert rates.get_rate("USD", "BTC")["rate"] == pytest.approx(1 / 60000)
    assert rates.get_rate("BTC", "EUR")["rate"] == pytest.approx(60000 / 1.1)
    assert rates.get_rate("USD", "USD")["rate"] == 1


def test_expiration_and_missing():
    db = DatabaseManager()
    with pytest.raises(ApiRequestError):
        RateService(auto_refresh=False).get_rate("BTC", "USD")
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    db.write("rates.json", {"pairs": {"BTC_USD": {"rate": 50000, "updated_at": old}}})
    with pytest.raises(ApiRequestError, match="устарел"):
        RateService(auto_refresh=False).get_rate("BTC", "USD")


def test_cached_rate_still_checks_timestamp(service):
    service.rates.auto_refresh = False
    assert service.rates.get_rate("BTC", "USD")["rate"] == 60000
    future = datetime.now(UTC) + timedelta(hours=1)
    with patch("valutatrade_hub.core.rates.datetime") as clock:
        clock.now.return_value = future
        with pytest.raises(ApiRequestError, match="устарел"):
            service.rates.get_rate("BTC", "USD")


def test_cache_closure():
    cache = create_cacher(5)
    calls = []
    with patch("valutatrade_hub.core.utils.time.monotonic", return_value=0):
        assert cache("x", lambda: calls.append(1) or 42) == 42
        assert cache("x", lambda: 99) == 42
    with patch("valutatrade_hub.core.utils.time.monotonic", return_value=6):
        assert cache("x", lambda: 99) == 99
    assert calls == [1]


def test_singletons_and_corrupted_json():
    assert DatabaseManager() is DatabaseManager()
    assert SettingsLoader() is SettingsLoader()
    db = DatabaseManager()
    db.write("users.json", [])
    db.path("users.json").write_text("{broken")
    with pytest.raises(StorageError):
        db.read("users.json", [])


def test_atomic_write_preserves_previous_file():
    db = DatabaseManager()
    db.write("users.json", [{"user_id": 1}])
    with patch("valutatrade_hub.infra.database.os.replace", side_effect=OSError):
        with pytest.raises(StorageError):
            db.write("users.json", [{"user_id": 2}])
    assert db.read("users.json", []) == [{"user_id": 1}]
    assert not list(db.path("users.json").parent.glob("*.tmp"))


def test_expired_rate_auto_refreshes():
    rates = RateService()
    with patch("valutatrade_hub.parser_service.updater.make_updater") as factory:
        factory.return_value.run_update.side_effect = lambda: make_updater(
            demo=True
        ).run_update()
        assert rates.get_rate("BTC", "USD")["rate"] == 60000
        factory.return_value.run_update.assert_called_once()


def test_failed_auto_refresh_has_actionable_message():
    with patch("valutatrade_hub.parser_service.updater.make_updater") as factory:
        factory.return_value.run_update.side_effect = ApiRequestError("нет сети")
        with pytest.raises(ApiRequestError, match="Повторите позже"):
            RateService().get_rate("BTC", "USD")
