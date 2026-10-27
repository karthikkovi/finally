"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point DB_PATH at a fresh temp SQLite file for the duration of a test."""
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    return db_file


class FakeMarketSource:
    """In-memory MarketDataSource stand-in that records add/remove calls."""

    def __init__(self, tickers=()):
        self.tickers = list(tickers)
        self.added: list[str] = []
        self.removed: list[str] = []

    async def start(self, tickers):
        self.tickers = list(tickers)

    async def stop(self):
        pass

    async def add_ticker(self, ticker):
        self.added.append(ticker)
        if ticker not in self.tickers:
            self.tickers.append(ticker)

    async def remove_ticker(self, ticker):
        self.removed.append(ticker)
        if ticker in self.tickers:
            self.tickers.remove(ticker)

    def get_tickers(self):
        return list(self.tickers)


@pytest.fixture
def seeded_db(temp_db):
    from app import db

    db.init_db()
    return temp_db


@pytest.fixture
def cache():
    from app.market import PriceCache

    c = PriceCache()
    c.update("AAPL", 100.0)
    c.update("MSFT", 400.0)
    return c


@pytest.fixture
def fake_source(seeded_db):
    from app import db

    return FakeMarketSource(db.get_watchlist())
