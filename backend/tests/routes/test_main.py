"""Full app: lifespan wiring, SSE route, and static SPA serving."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db


@pytest.fixture
def app_client(seeded_db, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    monkeypatch.setenv("LLM_MOCK", "true")
    from app.main import app, price_cache

    for ticker in list(price_cache.get_all()):
        price_cache.remove(ticker)
    with TestClient(app) as c:
        yield c


def test_lifespan_starts_market_source_and_snapshot(app_client):
    state = app_client.app.state
    assert state.market_source.get_tickers() == db.DEFAULT_TICKERS
    assert len(state.price_cache) == 10
    assert len(app_client.get("/api/portfolio/history").json()["snapshots"]) == 1


def test_all_routers_mounted(app_client):
    paths = set(app_client.get("/openapi.json").json()["paths"])
    assert {
        "/api/health",
        "/api/portfolio",
        "/api/portfolio/trade",
        "/api/portfolio/history",
        "/api/watchlist",
        "/api/watchlist/{ticker}",
        "/api/stream/prices",
        "/api/chat",
        "/api/chat/history",
    } <= paths


def test_end_to_end_trade_and_chat(app_client):
    r = app_client.post(
        "/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"}
    )
    assert r.status_code == 200
    r = app_client.post("/api/chat", json={"message": "buy 1 MSFT"})
    assert r.status_code == 200
    assert r.json()["trades"][0]["status"] == "executed"
    tickers = {p["ticker"] for p in app_client.get("/api/portfolio").json()["positions"]}
    assert tickers == {"AAPL", "MSFT"}


def test_added_ticker_gets_priced(app_client):
    assert app_client.post("/api/watchlist", json={"ticker": "PYPL"}).status_code == 201
    rows = {t["ticker"]: t for t in app_client.get("/api/watchlist").json()["tickers"]}
    assert rows["PYPL"]["price"] is not None


def test_held_ticker_tracked_on_restart(seeded_db, monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    db.upsert_position("PYPL", 2, 50.0)
    from app.main import app

    with TestClient(app) as c:
        assert "PYPL" in c.app.state.market_source.get_tickers()


@pytest.fixture
def spa_client(tmp_path):
    from app.main import _mount_static

    (tmp_path / "index.html").write_text("INDEX")
    (tmp_path / "about.html").write_text("ABOUT")
    (tmp_path / "_next").mkdir()
    (tmp_path / "_next" / "app.js").write_text("JS")
    app = FastAPI()

    @app.get("/api/health")
    def h():
        return {"status": "ok"}

    _mount_static(app, tmp_path)
    return TestClient(app)


def test_spa_serves_files_and_fallback(spa_client):
    assert spa_client.get("/").text == "INDEX"
    assert spa_client.get("/_next/app.js").text == "JS"
    assert spa_client.get("/about").text == "ABOUT"
    assert spa_client.get("/some/client/route").text == "INDEX"
    assert spa_client.get("/api/health").json() == {"status": "ok"}


def test_spa_does_not_swallow_api_404(spa_client):
    r = spa_client.get("/api/nope")
    assert r.status_code == 404
    assert r.json() == {"detail": "Not Found"}


def test_spa_blocks_path_traversal(spa_client, tmp_path):
    (tmp_path.parent / "secret.txt").write_text("SECRET")
    assert "SECRET" not in spa_client.get("/..%2Fsecret.txt").text
