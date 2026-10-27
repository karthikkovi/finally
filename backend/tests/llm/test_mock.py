"""Deterministic mock LLM (contract in planning/TEAM.md)."""

import pytest

from app.llm.mock import DEFAULT_MESSAGE, mock_response


@pytest.mark.parametrize(
    "text, side, qty, ticker, message",
    [
        ("buy 5 AAPL", "buy", 5.0, "AAPL", "Mock: buying 5 AAPL."),
        ("Please BUY 10 tsla now", "buy", 10.0, "TSLA", "Mock: buying 10 TSLA."),
        ("sell 2 nvda", "sell", 2.0, "NVDA", "Mock: selling 2 NVDA."),
        ("sell 0.5 MSFT", "sell", 0.5, "MSFT", "Mock: selling 0.5 MSFT."),
        ("buy 1 BRK.B", "buy", 1.0, "BRK.B", "Mock: buying 1 BRK.B."),
    ],
)
def test_trades(text, side, qty, ticker, message):
    r = mock_response(text)
    assert r.message == message
    assert [(t.side, t.quantity, t.ticker) for t in r.trades] == [(side, qty, ticker)]
    assert r.watchlist_changes == []


@pytest.mark.parametrize(
    "text, action, ticker",
    [
        ("add PYPL", "add", "PYPL"),
        ("watch amd", "add", "AMD"),
        ("Remove NFLX", "remove", "NFLX"),
        ("unwatch v", "remove", "V"),
    ],
)
def test_watchlist(text, action, ticker):
    r = mock_response(text)
    assert [(c.action, c.ticker) for c in r.watchlist_changes] == [(action, ticker)]
    assert r.trades == []
    assert ticker in r.message and r.message.startswith("Mock:")


@pytest.mark.parametrize("text", ["hello", "how is my portfolio?", "buy some apple", ""])
def test_default(text):
    r = mock_response(text)
    assert r.message == DEFAULT_MESSAGE
    assert r.trades == [] and r.watchlist_changes == []


def test_deterministic():
    assert mock_response("buy 3 AAPL") == mock_response("buy 3 AAPL")
