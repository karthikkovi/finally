"""Watchlist service: validation, DB, and market source sync."""

import pytest

from app import db
from app.market import PriceCache
from app.services import (
    add_watchlist_ticker,
    execute_trade,
    get_watchlist_with_prices,
    normalize_ticker,
    remove_watchlist_ticker,
    tracked_tickers,
)

pytestmark = pytest.mark.usefixtures("seeded_db")


@pytest.mark.parametrize("raw,expected", [("aapl", "AAPL"), (" brk.b ", "BRK.B"), ("V", "V")])
def test_normalize_valid(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "AB1", "TOOLONGTICKER", "A-B", None])
def test_normalize_invalid(raw):
    with pytest.raises(ValueError, match="Invalid ticker"):
        normalize_ticker(raw)


async def test_add_ticker(fake_source):
    assert await add_watchlist_ticker("pypl", fake_source) is True
    assert db.get_watchlist()[-1] == "PYPL"
    assert "PYPL" in fake_source.get_tickers()


async def test_add_duplicate_returns_false(fake_source):
    assert await add_watchlist_ticker("AAPL", fake_source) is False
    assert db.get_watchlist().count("AAPL") == 1


async def test_add_invalid_raises(fake_source):
    with pytest.raises(ValueError):
        await add_watchlist_ticker("123", fake_source)
    assert fake_source.added == []


async def test_remove_present_and_absent(fake_source):
    assert await remove_watchlist_ticker("nflx", fake_source) is True
    assert "NFLX" not in db.get_watchlist()
    assert fake_source.removed == ["NFLX"]
    assert await remove_watchlist_ticker("NFLX", fake_source) is False


async def test_remove_keeps_streaming_held_position(fake_source, cache):
    execute_trade("AAPL", "buy", 1, cache)
    assert await remove_watchlist_ticker("AAPL", fake_source) is True
    assert fake_source.removed == []
    assert "AAPL" in tracked_tickers()


def test_tracked_tickers_is_watchlist_union_positions(cache):
    cache.update("PYPL", 50.0)
    execute_trade("PYPL", "buy", 1, cache)
    tracked = tracked_tickers()
    assert tracked[:10] == db.DEFAULT_TICKERS
    assert tracked[10:] == ["PYPL"]


def test_watchlist_with_prices():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("AAPL", 191.0)
    rows = {r["ticker"]: r for r in get_watchlist_with_prices(cache)}
    assert list(rows) == db.DEFAULT_TICKERS
    assert rows["AAPL"] == {
        "ticker": "AAPL",
        "price": 191.0,
        "previous_price": 190.0,
        "change": 1.0,
        "change_percent": pytest.approx(0.5263, abs=1e-4),
        "direction": "up",
        "open_price": 190.0,
        "change_percent_open": pytest.approx(0.5263, abs=1e-4),
    }
    assert rows["MSFT"]["price"] is None
    assert set(rows["MSFT"]) == set(rows["AAPL"])
