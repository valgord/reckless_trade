from pathlib import Path

import pytest

from platform_core.settings import load_settings


def test_load_demo_settings(monkeypatch):
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    settings = load_settings("demo", Path(__file__).parents[1])
    assert settings.mode == "demo"
    assert settings.venue == "BYBIT"


def test_live_is_locked(monkeypatch):
    monkeypatch.delenv("ALLOW_LIVE_TRADING", raising=False)
    with pytest.raises(RuntimeError):
        load_settings("live", Path(__file__).parents[1])
