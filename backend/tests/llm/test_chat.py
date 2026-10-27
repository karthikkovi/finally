"""Chat orchestration: action execution, failure reporting, persistence."""

from app import db
from app.llm import chat
from app.llm.models import LLMResponse, TradeAction, WatchlistChange
from app.services import TradeError


async def test_mock_buy_executes_and_persists(chat_db, price_cache, market_source, mock_llm):
    result = await chat.handle_chat("buy 5 AAPL", price_cache, market_source)

    assert result["message"] == "Mock: buying 5 AAPL."
    assert result["trades"] == [
        {"ticker": "AAPL", "side": "buy", "quantity": 5.0, "status": "executed", "price": 190.0}
    ]
    assert result["watchlist_changes"] == []
    assert db.get_cash_balance() == 10000.0 - 5 * 190.0
    assert db.get_position("AAPL")["quantity"] == 5

    messages = db.get_chat_messages()
    assert [(m["role"], m["content"]) for m in messages] == [
        ("user", "buy 5 AAPL"),
        ("assistant", "Mock: buying 5 AAPL."),
    ]
    assert messages[0]["actions"] is None
    assert messages[1]["actions"]["trades"][0]["status"] == "executed"


async def test_mock_failed_trade_reports_error(chat_db, price_cache, market_source, mock_llm):
    result = await chat.handle_chat("sell 5 AAPL", price_cache, market_source)
    trade = result["trades"][0]
    assert trade["status"] == "failed"
    assert trade["error"]
    assert "price" not in trade
    assert db.get_cash_balance() == 10000.0


async def test_insufficient_cash(chat_db, price_cache, market_source, mock_llm):
    result = await chat.handle_chat("buy 1000 MSFT", price_cache, market_source)
    assert result["trades"][0]["status"] == "failed"
    assert db.get_position("MSFT") is None


async def test_mock_watchlist_add_and_remove(chat_db, price_cache, market_source, mock_llm):
    result = await chat.handle_chat("add PYPL", price_cache, market_source)
    assert result["watchlist_changes"] == [{"ticker": "PYPL", "action": "add", "status": "applied"}]
    assert "PYPL" in db.get_watchlist()

    again = await chat.handle_chat("add PYPL", price_cache, market_source)
    assert again["watchlist_changes"][0]["status"] == "failed"

    removed = await chat.handle_chat("remove PYPL", price_cache, market_source)
    assert removed["watchlist_changes"][0]["status"] == "applied"
    assert "PYPL" not in db.get_watchlist()

    missing = await chat.handle_chat("unwatch PYPL", price_cache, market_source)
    assert missing["watchlist_changes"][0]["status"] == "failed"
    assert missing["watchlist_changes"][0]["error"]


async def test_mock_plain_message_has_no_actions(chat_db, price_cache, market_source, mock_llm):
    result = await chat.handle_chat("hello", price_cache, market_source)
    assert result == {
        "message": "Mock response: I can help you analyze your portfolio.",
        "trades": [],
        "watchlist_changes": [],
    }
    assert db.get_chat_messages()[-1]["actions"] is None


async def test_trade_error_is_caught(chat_db, price_cache, market_source, real_llm, monkeypatch):
    monkeypatch.setattr(
        chat,
        "call_llm",
        lambda messages: LLMResponse(
            message="Buying",
            trades=[TradeAction(ticker="aapl", side="buy", quantity=1)],
        ),
    )

    def failing_trade(*args, **kwargs):
        raise TradeError("Insufficient cash: need $190.00, have $0.00")

    monkeypatch.setattr(chat, "execute_trade", failing_trade)
    result = await chat.handle_chat("buy apple", price_cache, market_source)
    assert result["trades"] == [
        {
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 1.0,
            "status": "failed",
            "error": "Insufficient cash: need $190.00, have $0.00",
        }
    ]


async def test_unexpected_errors_never_raise(
    chat_db, price_cache, market_source, real_llm, monkeypatch
):
    monkeypatch.setattr(
        chat,
        "call_llm",
        lambda messages: LLMResponse(
            message="ok",
            trades=[TradeAction(ticker="AAPL", side="buy", quantity=1)],
            watchlist_changes=[WatchlistChange(ticker="AMD", action="add")],
        ),
    )

    def explode(*args, **kwargs):
        raise RuntimeError("db locked")

    monkeypatch.setattr(chat, "execute_trade", explode)
    monkeypatch.setattr(chat, "add_watchlist_ticker", explode)
    result = await chat.handle_chat("go", price_cache, market_source)
    assert result["trades"][0]["status"] == "failed"
    assert result["watchlist_changes"][0]["status"] == "failed"


async def test_real_mode_builds_prompt_with_context_and_history(
    chat_db, price_cache, market_source, real_llm, monkeypatch
):
    db.insert_chat_message("user", "earlier question", None)
    db.insert_chat_message("assistant", "earlier answer", None)
    captured = {}

    def fake_call(messages):
        captured["messages"] = messages
        return LLMResponse(message="analysis")

    monkeypatch.setattr(chat, "call_llm", fake_call)
    result = await chat.handle_chat("how am I doing?", price_cache, market_source)

    assert result["message"] == "analysis"
    msgs = captured["messages"]
    assert msgs[0]["role"] == "system" and "FinAlly" in msgs[0]["content"]
    assert "Cash: $10,000.00" in msgs[1]["content"]
    assert "AAPL: $190.00" in msgs[1]["content"]
    assert [m["content"] for m in msgs[2:]] == [
        "earlier question",
        "earlier answer",
        "how am I doing?",
    ]


async def test_llm_preparation_failure_returns_message(
    chat_db, price_cache, market_source, real_llm, monkeypatch
):
    def broken_context(cache):
        raise RuntimeError("boom")

    monkeypatch.setattr(chat, "build_portfolio_context", broken_context)
    result = await chat.handle_chat("hi", price_cache, market_source)
    assert result["trades"] == [] and result["message"]


async def test_history_includes_previous_action_results(
    chat_db, price_cache, market_source, real_llm, monkeypatch
):
    db.insert_chat_message("user", "buy 1000 TSLA", None)
    db.insert_chat_message(
        "assistant",
        "Buying 1000 TSLA.",
        {
            "trades": [
                {
                    "ticker": "TSLA",
                    "side": "buy",
                    "quantity": 1000,
                    "status": "failed",
                    "error": "Insufficient cash",
                },
                {
                    "ticker": "AAPL",
                    "side": "buy",
                    "quantity": 1,
                    "status": "executed",
                    "price": 190.0,
                },
            ],
            "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "applied"}],
        },
    )
    captured = {}

    def fake_call(messages):
        captured["messages"] = messages
        return LLMResponse(message="ok")

    monkeypatch.setattr(chat, "call_llm", fake_call)
    await chat.handle_chat("what happened?", price_cache, market_source)

    assistant = captured["messages"][3]["content"]
    assert assistant.startswith("Buying 1000 TSLA.")
    assert "buy 1000 TSLA FAILED: Insufficient cash" in assistant
    assert "buy 1 AAPL executed at $190.00" in assistant
    assert "watchlist add PYPL applied" in assistant
