"""REST endpoints: status codes and response shapes per planning/TEAM.md."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import health, portfolio, watchlist

PORTFOLIO_KEYS = {"cash_balance", "total_value", "positions_value", "unrealized_pnl", "positions"}
POSITION_KEYS = {
    "ticker",
    "quantity",
    "avg_cost",
    "current_price",
    "market_value",
    "unrealized_pnl",
    "unrealized_pnl_percent",
}
WATCH_KEYS = {
    "ticker",
    "price",
    "previous_price",
    "change",
    "change_percent",
    "direction",
    "open_price",
    "change_percent_open",
}


@pytest.fixture
def client(cache, fake_source):
    app = FastAPI()
    for module in (health, portfolio, watchlist):
        app.include_router(module.router)
    app.state.price_cache = cache
    app.state.market_source = fake_source
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_get_portfolio(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == PORTFOLIO_KEYS
    assert body["cash_balance"] == 10000.0
    assert body["positions"] == []


def test_trade_buy_then_sell(client):
    r = client.post("/api/portfolio/trade", json={"ticker": "aapl", "quantity": 5, "side": "buy"})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"trade", "portfolio"}
    assert set(body["trade"]) >= {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert body["trade"]["ticker"] == "AAPL"
    assert body["portfolio"]["cash_balance"] == 9500.0
    assert set(body["portfolio"]["positions"][0]) == POSITION_KEYS

    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 5, "side": "sell"})
    assert r.status_code == 200
    assert r.json()["portfolio"]["positions"] == []
    assert r.json()["portfolio"]["cash_balance"] == 10000.0


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({"ticker": "AAPL", "quantity": 1000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "AAPL", "quantity": 1, "side": "sell"}, "Insufficient shares"),
        ({"ticker": "AAPL", "quantity": 0, "side": "buy"}, "greater than 0"),
        ({"ticker": "AAPL", "quantity": -2, "side": "buy"}, "greater than 0"),
        ({"ticker": "AAPL", "quantity": 1, "side": "hold"}, "Invalid side"),
        ({"ticker": "ZZZZ", "quantity": 1, "side": "buy"}, "No price available"),
    ],
)
def test_trade_validation_400(client, payload, fragment):
    r = client.post("/api/portfolio/trade", json=payload)
    assert r.status_code == 400
    assert fragment in r.json()["detail"]


def test_trade_malformed_body_422(client):
    assert client.post("/api/portfolio/trade", json={"ticker": "AAPL"}).status_code == 422
    r = client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": "x", "side": "buy"})
    assert r.status_code == 422


def test_history(client):
    assert client.get("/api/portfolio/history").json() == {"snapshots": []}
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    snaps = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snaps) == 1
    assert set(snaps[0]) >= {"total_value", "recorded_at"}


def test_get_watchlist(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    tickers = r.json()["tickers"]
    assert len(tickers) == 10
    assert all(set(t) == WATCH_KEYS for t in tickers)
    by = {t["ticker"]: t for t in tickers}
    assert by["AAPL"]["price"] == 100.0
    assert by["NFLX"]["price"] is None


def test_add_watchlist(client, fake_source):
    r = client.post("/api/watchlist", json={"ticker": "pypl"})
    assert r.status_code == 201
    assert r.json() == {"ticker": "PYPL"}
    assert "PYPL" in fake_source.get_tickers()
    assert "PYPL" in [t["ticker"] for t in client.get("/api/watchlist").json()["tickers"]]


def test_add_watchlist_duplicate_409(client):
    r = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert r.status_code == 409
    assert "already" in r.json()["detail"]


@pytest.mark.parametrize("ticker", ["", "12", "WAYTOOLONGTICKER", "A B"])
def test_add_watchlist_invalid_400(client, ticker):
    r = client.post("/api/watchlist", json={"ticker": ticker})
    assert r.status_code == 400
    assert "Invalid ticker" in r.json()["detail"]


def test_add_watchlist_missing_body_422(client):
    assert client.post("/api/watchlist", json={}).status_code == 422


def test_delete_watchlist(client, fake_source):
    r = client.delete("/api/watchlist/nflx")
    assert r.status_code == 204
    assert r.content == b""
    assert "NFLX" not in fake_source.get_tickers()
    r = client.delete("/api/watchlist/NFLX")
    assert r.status_code == 404
    assert "not on the watchlist" in r.json()["detail"]


def test_delete_watchlist_invalid_400(client):
    assert client.delete("/api/watchlist/1234").status_code == 400
