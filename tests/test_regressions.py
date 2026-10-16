"""Регрессии: дробные суммы, повреждённые данные и независимость источников."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from valutatrade_hub.cli.interface import CommandInterface, make_parser
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    InsufficientFundsError,
    StorageError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.core.utils import utc_now
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    DemoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


def test_fractional_balance_can_be_sold_completely():
    service = WalletService()
    service.register("alice", "secret")
    service.login("alice", "secret")
    service.buy("USD", 0.3)
    for _ in range(3):
        service.sell("USD", 0.1)
    assert service.show_portfolio()["total"] == 0
    wallet = Wallet("BTC", 0.00000001)
    with pytest.raises(InsufficientFundsError):
        wallet.withdraw(0.000000011)


def test_missing_wallet_does_not_call_api():
    service = WalletService()
    service.register("alice", "secret")
    service.login("alice", "secret")
    with patch.object(
        service.rates, "get_rate", side_effect=ApiRequestError("нет сети")
    ) as get:
        with pytest.raises(ValueError, match="нет кошелька"):
            service.sell("BTC", 1)
    get.assert_not_called()


def test_portfolio_resolves_owner():
    user = WalletService().register("alice", "secret")
    assert Portfolio(user.user_id).user.username == "alice"


def test_portfolio_rejects_another_owner():
    with pytest.raises(ValueError):
        Portfolio(1, user=User.create(2, "bob", "secret"))


def test_configured_base_applies_to_cli_and_service(tmp_path, monkeypatch):
    config = tmp_path / "config.toml"
    config.write_text('[tool.valutatrade]\nbase_currency = "EUR"\n')
    monkeypatch.setenv("VALUTATRADE_CONFIG", str(config))
    SettingsLoader().reload()
    service = WalletService()
    service.register("alice", "secret")
    service.login("alice", "secret")
    assert service.show_portfolio()["base"] == "EUR"
    assert make_parser().parse_args(["show-portfolio"]).base == "EUR"
    assert make_parser().parse_args(["show-rates"]).base == "EUR"
    assert make_parser().parse_args(["show-portfolio", "--base", "USD"]).base == "USD"


@pytest.mark.parametrize("contents", [[{}], [None], [{"user_id": "wrong"}]])
def test_bad_user_records_do_not_crash_console(contents, capsys):
    db = DatabaseManager()
    db.write("users.json", contents)
    before = db.path("users.json").read_bytes()
    cli = CommandInterface()
    assert cli.execute("register --username alice --password secret")
    assert "users.json" in capsys.readouterr().out
    assert db.path("users.json").read_bytes() == before
    assert cli.execute("help")


def test_bad_wallet_record_does_not_crash_console(capsys):
    cli = CommandInterface()
    cli.execute("register --username alice --password secret")
    cli.execute("login --username alice --password secret")
    db = DatabaseManager()
    db.write("portfolios.json", [{"user_id": 1, "wallets": {"BTC": None}}])
    before = db.path("portfolios.json").read_bytes()
    cli.execute("show-portfolio")
    assert "portfolios.json" in capsys.readouterr().out
    assert db.path("portfolios.json").read_bytes() == before


def test_bad_pairs_do_not_crash_console(capsys):
    DatabaseManager().write("rates.json", {"pairs": ["BTC_USD"]})
    CommandInterface().execute("get-rate --from BTC --to USD")
    assert "rates.json" in capsys.readouterr().out


def test_malformed_provider_does_not_block_valid_provider():
    bad = Mock(source="bad-date", updated_at="not-a-date")
    bad.fetch_rates.return_value = {"EUR_USD": 1.2}
    result = RatesUpdater([DemoClient(), bad]).run_update()
    assert result["updated"] == 6
    assert len(result["errors"]) == 1
    assert DatabaseManager().read("rates.json", {})["pairs"]["EUR_USD"]["rate"] == 1.1


def test_newest_source_wins_regardless_of_client_order():
    new = Mock(source="new", updated_at=utc_now())
    new.fetch_rates.return_value = {"EUR_USD": 1.2}
    old = Mock(
        source="old", updated_at=(datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    )
    old.fetch_rates.return_value = {"EUR_USD": 1.0}
    RatesUpdater([new, old]).run_update()
    assert DatabaseManager().read("rates.json", {})["pairs"]["EUR_USD"]["rate"] == 1.2


def test_fiat_bad_nested_response_is_api_error():
    client = ExchangeRateApiClient(ParserConfig(EXCHANGERATE_API_KEY="test"))
    with patch.object(
        client,
        "_get",
        return_value={"result": "success", "base_code": "USD", "conversion_rates": []},
    ):
        with pytest.raises(ApiRequestError):
            client.fetch_rates()


def test_history_id_and_recovery_after_snapshot_failure():
    db = DatabaseManager()
    storage = RatesStorage()
    stamp = utc_now()
    update = {"EUR_USD": {"rate": 1.2, "updated_at": stamp, "source": "test"}}
    original = db.write

    def fail_snapshot(name, data):
        if name == "rates.json":
            raise OSError("disk error")
        return original(name, data)

    with patch.object(db, "write", side_effect=fail_snapshot), pytest.raises(OSError):
        storage.save(update)
    storage.save(update)
    history = db.read("exchange_rates.json", [])
    assert len(history) == 1
    assert history[0]["id"] == f"EUR_USD_{stamp}"


def test_fresh_inverse_is_used_when_direct_quote_expired():
    now = utc_now()
    old = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    DatabaseManager().write(
        "rates.json",
        {
            "pairs": {
                "EUR_USD": {"rate": 1.2, "updated_at": old},
                "USD_EUR": {"rate": 0.8, "updated_at": now},
            }
        },
    )
    assert RateService(auto_refresh=False).get_rate("EUR", "USD")["rate"] == 1.25


def test_separate_processes_do_not_lose_updates():
    db = DatabaseManager()
    db.write("counter.json", {"value": 0})
    script = """
import time
from valutatrade_hub.infra.database import DatabaseManager
db = DatabaseManager()
for _ in range(20):
    with db.lock:
        row = db.read("counter.json", {})
        time.sleep(0.004)
        row["value"] += 1
        db.write("counter.json", row)
"""

    def worker(_):
        return subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=20
        )

    with ThreadPoolExecutor(max_workers=3) as executor:
        for result in executor.map(worker, range(3)):
            assert result.returncode == 0, result.stderr
    assert json.loads(db.path("counter.json").read_text())["value"] == 60


@pytest.mark.parametrize(
    "rates", [[], {"BTC_USD": None}, {"BAD_USD": 1}, {"BTC_USD": float("nan")}]
)
def test_invalid_provider_batch_does_not_remove_other_rates(rates):
    client = Mock(source="malformed", updated_at=utc_now())
    client.fetch_rates.return_value = rates
    result = RatesUpdater([DemoClient(), client]).run_update()
    assert result["updated"] == 6
    assert len(result["errors"]) == 1


def test_future_timestamp_does_not_poison_snapshot():
    client = Mock(source="future", updated_at="2099-01-01T00:00:00Z")
    client.fetch_rates.return_value = {"BTC_USD": 1}
    result = RatesUpdater([client, DemoClient()]).run_update()
    assert len(result["errors"]) == 1
    assert RateService(auto_refresh=False).get_rate("BTC", "USD")["rate"] == 60000


def test_crypto_currencies_keep_their_own_timestamps():
    now = int(datetime.now(UTC).timestamp())
    client = CoinGeckoClient()
    data = {
        "bitcoin": {"usd": 60000, "last_updated_at": now - 3600},
        "ethereum": {"usd": 3000, "last_updated_at": now},
        "solana": {"usd": 150, "last_updated_at": now},
    }
    with patch.object(client, "_get", return_value=data):
        RatesUpdater([client]).run_update()
    rates = RateService(auto_refresh=False)
    assert rates.get_rate("ETH", "USD")["rate"] == 3000
    with pytest.raises(ApiRequestError, match="устарел"):
        rates.get_rate("BTC", "USD")


def test_atomic_replacement_invalidates_cache_even_with_equal_mtime():
    db = DatabaseManager()
    RatesUpdater([DemoClient()]).run_update()
    rates = RateService(auto_refresh=False)
    assert rates.get_rate("BTC", "USD")["rate"] == 60000
    stamp = db.path("rates.json").stat().st_mtime_ns
    snapshot = db.read("rates.json", {})
    snapshot["pairs"]["BTC_USD"]["rate"] = 70000
    db.write("rates.json", snapshot)
    os.utime(db.path("rates.json"), ns=(stamp, stamp))
    assert rates.get_rate("BTC", "USD")["rate"] == 70000


def test_registration_rolls_back_portfolio_on_write_failure():
    service = WalletService()
    service.register("alice", "secret")
    db = service.db
    before = {
        name: db.path(name).read_bytes() for name in ("users.json", "portfolios.json")
    }
    original = db.write

    def fail_users(name, data):
        if name == "users.json":
            raise StorageError("disk error")
        return original(name, data)

    with patch.object(db, "write", side_effect=fail_users), pytest.raises(StorageError):
        service.register("bob", "secret")
    for name, contents in before.items():
        assert db.path(name).read_bytes() == contents


def test_failed_settings_reload_preserves_working_configuration(monkeypatch):
    settings = SettingsLoader()
    ttl = settings.get("rates_ttl_seconds")
    monkeypatch.setenv("VALUTATRADE_RATES_TTL", "-1")
    with pytest.raises(ValueError):
        settings.reload()
    assert settings.get("rates_ttl_seconds") == ttl
