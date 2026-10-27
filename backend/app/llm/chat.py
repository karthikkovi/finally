"""Chat orchestration: build prompt, call (or mock) the LLM, execute actions, persist."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os

from app import db
from app.services import TradeError, add_watchlist_ticker, execute_trade, remove_watchlist_ticker

from .client import call_llm
from .mock import mock_response
from .models import LLMResponse, TradeAction, WatchlistChange
from .prompt import HISTORY_LIMIT, build_messages, build_portfolio_context

logger = logging.getLogger(__name__)

PREPARE_FAILED_MESSAGE = (
    "Sorry, something went wrong preparing your request. No actions were taken."
)


def is_mock_mode() -> bool:
    return os.getenv("LLM_MOCK", "").strip().lower() == "true"


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


def _execute_trade(trade: TradeAction, price_cache) -> dict:
    ticker = trade.ticker.strip().upper()
    result = {"ticker": ticker, "side": trade.side, "quantity": trade.quantity}
    try:
        executed = execute_trade(ticker, trade.side, trade.quantity, price_cache)
    except TradeError as exc:
        return {**result, "status": "failed", "error": str(exc)}
    except Exception as exc:
        logger.exception("Unexpected error executing trade %s", result)
        return {**result, "status": "failed", "error": f"Trade failed: {exc}"}
    return {**result, "status": "executed", "price": executed.get("price")}


async def _apply_watchlist_change(change: WatchlistChange, market_source) -> dict:
    ticker = change.ticker.strip().upper()
    result = {"ticker": ticker, "action": change.action}
    try:
        if change.action == "add":
            ok = await _maybe_await(add_watchlist_ticker(ticker, market_source))
            error = f"{ticker} is already on the watchlist"
        else:
            ok = await _maybe_await(remove_watchlist_ticker(ticker, market_source))
            error = f"{ticker} is not on the watchlist"
    except Exception as exc:  # invalid ticker (ValueError/TradeError) or source failure
        return {**result, "status": "failed", "error": str(exc) or "Watchlist change failed"}
    if not ok:
        return {**result, "status": "failed", "error": error}
    return {**result, "status": "applied"}


async def _get_llm_response(user_message: str, price_cache) -> LLMResponse:
    if is_mock_mode():
        return mock_response(user_message)
    history = db.get_chat_messages(limit=HISTORY_LIMIT)
    context = build_portfolio_context(price_cache)
    messages = build_messages(user_message, history, context)
    return await asyncio.to_thread(call_llm, messages)


async def handle_chat(user_message: str, price_cache, market_source) -> dict:
    """Process one chat turn and return the /api/chat response body."""
    try:
        llm_response = await _get_llm_response(user_message, price_cache)
    except Exception:
        logger.exception("Failed to prepare LLM request")
        llm_response = LLMResponse(message=PREPARE_FAILED_MESSAGE)

    db.insert_chat_message("user", user_message, None)

    trades = [_execute_trade(t, price_cache) for t in llm_response.trades]
    watchlist_changes = [
        await _apply_watchlist_change(c, market_source) for c in llm_response.watchlist_changes
    ]

    actions = None
    if trades or watchlist_changes:
        actions = {"trades": trades, "watchlist_changes": watchlist_changes}
    db.insert_chat_message("assistant", llm_response.message, actions)

    return {
        "message": llm_response.message,
        "trades": trades,
        "watchlist_changes": watchlist_changes,
    }
