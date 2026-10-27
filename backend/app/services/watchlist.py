"""Watchlist management that keeps the market data source in sync."""

from __future__ import annotations

import re

from app import db
from app.market import MarketDataSource, PriceCache

TICKER_RE = re.compile(r"^[A-Z.]{1,10}$")


def normalize_ticker(ticker: str) -> str:
    """Upper-case and validate a ticker symbol. Raises ValueError if invalid."""
    normalized = (ticker or "").strip().upper()
    if not TICKER_RE.match(normalized):
        raise ValueError(f"Invalid ticker '{ticker}': use 1-10 letters (A-Z or '.')")
    return normalized


def tracked_tickers() -> list[str]:
    """Watchlist ∪ held positions — everything the market source must price."""
    tickers = db.get_watchlist()
    for pos in db.get_positions():
        if pos["ticker"] not in tickers:
            tickers.append(pos["ticker"])
    return tickers


async def add_watchlist_ticker(ticker: str, market_source: MarketDataSource) -> bool:
    """Add to the watchlist and start streaming it. False if already present."""
    ticker = normalize_ticker(ticker)
    added = db.add_to_watchlist(ticker)
    await market_source.add_ticker(ticker)
    return added


async def remove_watchlist_ticker(ticker: str, market_source: MarketDataSource) -> bool:
    """Remove from the watchlist. Keeps streaming if a position is still held."""
    ticker = normalize_ticker(ticker)
    removed = db.remove_from_watchlist(ticker)
    if removed and db.get_position(ticker) is None:
        await market_source.remove_ticker(ticker)
    return removed


def get_watchlist_with_prices(price_cache: PriceCache) -> list[dict]:
    result = []
    for ticker in db.get_watchlist():
        update = price_cache.get(ticker)
        if update is None:
            result.append(
                {
                    "ticker": ticker,
                    "price": None,
                    "previous_price": None,
                    "change": None,
                    "change_percent": None,
                    "direction": None,
                    "open_price": None,
                    "change_percent_open": None,
                }
            )
        else:
            data = update.to_dict()
            data.pop("timestamp")
            result.append(data)
    return result
