"""Изолированное временное хранилище для каждого теста."""

import pytest

from valutatrade_hub.infra.settings import SettingsLoader


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv("VALUTATRADE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VALUTATRADE_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("VALUTATRADE_RATES_TTL", "300")
    SettingsLoader().reload()
    yield tmp_path
