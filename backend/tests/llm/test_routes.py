"""/api/chat routes with LLM_MOCK=true (no network)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.chat import router


@pytest.fixture
def client(chat_db, price_cache, market_source, mock_llm):
    app = FastAPI()
    app.include_router(router)
    app.state.price_cache = price_cache
    app.state.market_source = market_source
    with TestClient(app) as c:
        yield c


def test_post_chat_shape(client):
    resp = client.post("/api/chat", json={"message": "buy 2 TSLA"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"message", "trades", "watchlist_changes"}
    assert body["message"] == "Mock: buying 2 TSLA."
    assert body["trades"][0]["status"] == "executed"
    assert body["trades"][0]["price"] == 250.0


def test_post_chat_failed_trade_still_200(client):
    resp = client.post("/api/chat", json={"message": "sell 100 TSLA"})
    assert resp.status_code == 200
    assert resp.json()["trades"][0]["status"] == "failed"


def test_post_chat_validation(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={}).status_code == 422
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422


def test_history(client):
    assert client.get("/api/chat/history").json() == {"messages": []}
    client.post("/api/chat", json={"message": "add PYPL"})
    messages = client.get("/api/chat/history").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert set(messages[0]) >= {"id", "role", "content", "actions", "created_at"}
    assert messages[1]["actions"]["watchlist_changes"][0]["ticker"] == "PYPL"
