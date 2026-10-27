"""Fixtures for LLM/chat tests: temp DB, seeded price cache, fake market source."""

import pytest

from app import db
from app.market.cache import PriceCache


class FakeMarketSource:
    def __init__(self, tickers=()):
        self.tickers = list(tickers)

    async def start(self, tickers):
        self.tickers = list(tickers)

    async def stop(self):
        pass

    async def add_ticker(self, ticker):
        if ticker not in self.tickers:
            self.tickers.append(ticker)

    async def remove_ticker(self, ticker):
        if ticker in self.tickers:
            self.tickers.remove(ticker)

    def get_tickers(self):
        return list(self.tickers)


@pytest.fixture
def chat_db(temp_db):
    db.init_db()
    return temp_db


@pytest.fixture
def price_cache():
    cache = PriceCache()
    for ticker, price in {"AAPL": 190.0, "MSFT": 400.0, "TSLA": 250.0}.items():
        cache.update(ticker, price)
    return cache


@pytest.fixture
def market_source(chat_db):
    return FakeMarketSource(db.get_watchlist())


@pytest.fixture
def mock_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")


@pytest.fixture
def real_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
