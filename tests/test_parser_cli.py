"""API-контракты, частичные отказы и полный пользовательский сценарий."""

from unittest.mock import Mock, patch

import pytest
import requests

from valutatrade_hub.cli.interface import CommandInterface
from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.usecases import WalletService
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.logging_config import setup_logging
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    DemoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


def response(body, status=200):
    reply = Mock(status_code=status)
    reply.json.return_value = body
    return reply


def test_fiat_conversion_is_inverse():
    client = ExchangeRateApiClient(ParserConfig(EXCHANGERATE_API_KEY="test-secret"))
    with patch(
        "requests.get",
        return_value=response(
            {
                "result": "success",
                "base_code": "USD",
                "conversion_rates": {"EUR": 0.8, "GBP": 0.5, "RUB": 100},
            }
        ),
    ) as get:
        assert client.fetch_rates() == {"EUR_USD": 1.25, "GBP_USD": 2, "RUB_USD": 0.01}
    assert get.call_args.kwargs["timeout"] == 10


def test_crypto_format_and_request():
    with patch(
        "requests.get",
        return_value=response(
            {
                "bitcoin": {"usd": 60000},
                "ethereum": {"usd": 3000},
                "solana": {"usd": 150},
            }
        ),
    ) as get:
        assert CoinGeckoClient().fetch_rates()["BTC_USD"] == 60000
    assert get.call_args.kwargs["params"]["ids"] == "bitcoin,ethereum,solana"


@pytest.mark.parametrize("status", [401, 403, 429])
def test_api_status_errors(status):
    with patch("requests.get", return_value=response({}, status)):
        with pytest.raises(ApiRequestError):
            CoinGeckoClient().fetch_rates()


def test_timeout_hides_api_key():
    client = ExchangeRateApiClient(ParserConfig(EXCHANGERATE_API_KEY="test-secret"))
    with patch("requests.get", side_effect=requests.Timeout("URL/test-secret/latest")):
        with pytest.raises(ApiRequestError) as error:
            client.fetch_rates()
    assert "test-secret" not in str(error.value)


def test_partial_and_total_failure():
    broken = Mock(source="broken", updated_at=None)
    broken.fetch_rates.side_effect = ApiRequestError("недоступен")
    result = RatesUpdater([broken, DemoClient()]).run_update()
    assert result["updated"] == 6
    assert len(result["errors"]) == 1
    before = DatabaseManager().path("rates.json").read_bytes()
    with pytest.raises(ApiRequestError):
        RatesUpdater([broken]).run_update()
    assert DatabaseManager().path("rates.json").read_bytes() == before


def test_storage_ignores_old_values_and_duplicate_history():
    storage = RatesStorage()
    new = {
        "EUR_USD": {"rate": 1.2, "updated_at": "2025-10-10T10:00:00Z", "source": "test"}
    }
    old = {
        "EUR_USD": {"rate": 1.0, "updated_at": "2025-10-09T10:00:00Z", "source": "test"}
    }
    assert storage.save(new) == 1
    assert storage.save(new) == 0
    assert storage.save(old) == 0
    db = DatabaseManager()
    assert db.read("rates.json", {})["pairs"]["EUR_USD"]["rate"] == 1.2
    assert len(db.read("exchange_rates.json", [])) == 1


def test_cli_flow_and_persistence(capsys):
    cli = CommandInterface()
    commands = [
        'register --username "Alice Smith" --password secret',
        'login --username "Alice Smith" --password secret',
        "update-rates --demo",
        "buy --currency BTC --amount 0.05",
        "sell --currency BTC --amount 0.01",
        "show-portfolio",
        "get-rate --from USD --to BTC",
        "show-rates --top 2",
        "sell --currency BTC --amount 99",
        "get-rate --from ABC --to USD",
        "buy --currency BTC --amount nan",
        "bad-command",
    ]
    for command in commands:
        assert cli.execute(command)
    output = capsys.readouterr().out
    assert "Покупка выполнена" in output
    assert "Продажа выполнена" in output
    assert "ИТОГО: 2,400.00 USD" in output
    assert "Недостаточно средств" in output
    assert "Неизвестная валюта 'ABC'" in output
    assert "ДЕМО" in output
    assert not cli.execute("exit")
    restarted = WalletService()
    restarted.login("Alice Smith", "secret")
    assert restarted.show_portfolio()["total"] == pytest.approx(2400)


def test_confirmation_cancels_trade():
    cli = CommandInterface()
    with (
        patch("builtins.input", return_value="n"),
        patch.object(cli, "_trade") as trade,
    ):
        cli.execute("buy --currency BTC --amount 1 --confirm")
    trade.assert_not_called()


def test_logs_include_result_without_password(isolated_data):
    setup_logging()
    cli = CommandInterface()
    cli.execute("register --username alice --password secret-password")
    cli.execute("login --username alice --password secret-password")
    cli.execute("update-rates --demo")
    cli.execute("buy --currency BTC --amount 1")
    cli.execute("sell --currency BTC --amount 2")
    logs = (isolated_data / "logs/actions.log").read_text()
    assert "InsufficientFundsError" in logs
    assert '"result": "ERROR"' in logs
    assert "secret-password" not in logs


def test_console_logging_only_during_explicit_update(capsys, isolated_data):
    setup_logging()
    cli = CommandInterface()
    cli.execute("update-rates --demo")
    assert "INFO: Starting rates update" in capsys.readouterr().err
    with patch("valutatrade_hub.parser_service.updater.make_updater") as factory:
        factory.return_value = RatesUpdater([DemoClient()])
        DatabaseManager().write("rates.json", {"pairs": {}})
        cli.execute("get-rate --from BTC --to USD")
    output = capsys.readouterr()
    assert "Курс BTC→USD" in output.out
    assert "INFO:" not in output.err
    file_log = (isolated_data / "logs/parser.log").read_text()
    assert "Starting rates update" in file_log


def test_file_debug_masks_credentials(isolated_data, monkeypatch):
    monkeypatch.setenv("EXCHANGERATE_API_KEY", "test-private-key")
    setup_logging()
    client = ExchangeRateApiClient()
    with patch(
        "requests.get",
        side_effect=requests.Timeout(
            "https://v6.exchangerate-api.com/v6/test-private-key/latest/USD"
        ),
    ):
        with pytest.raises(ApiRequestError):
            RatesUpdater([client]).run_update()
    file_log = (isolated_data / "logs/parser.log").read_text()
    assert "test-private-key" not in file_log
    assert "[REDACTED]" in file_log
    assert "traceback" in file_log
    assert "DEBUG" in file_log
