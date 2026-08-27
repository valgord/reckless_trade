from datetime import datetime, timedelta, timezone

from domain.models import IntelligenceEvent
from intelligence.news.alpha import NewsAlpha


def event(available_offset=0):
    now = datetime.now(timezone.utc)
    return IntelligenceEvent("1", "src", "title", "summary", ("BTC",), "regulation", 0.8, 0.9, 0.8, 3600,
                             now - timedelta(minutes=2), now - timedelta(minutes=1), now, now + timedelta(seconds=available_offset))


def test_news_alpha_maps_asset_after_availability():
    now = datetime.now(timezone.utc) + timedelta(seconds=1)
    signals = NewsAlpha().generate(event(), {"BTC": "BTCUSDT"}, now=now)
    assert len(signals) == 1
    assert signals[0].instrument.symbol == "BTCUSDT"


def test_news_alpha_blocks_future_information():
    now = datetime.now(timezone.utc)
    assert NewsAlpha().generate(event(60), {"BTC": "BTCUSDT"}, now=now) == []
