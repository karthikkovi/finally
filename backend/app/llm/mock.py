"""Deterministic mock LLM used when LLM_MOCK=true (E2E tests, offline dev).

Behaviour is part of the team contract in planning/TEAM.md — keep it stable.
"""

from __future__ import annotations

import re

from .models import LLMResponse, TradeAction, WatchlistChange

DEFAULT_MESSAGE = "Mock response: I can help you analyze your portfolio."

_TRADE_RE = re.compile(r"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+([A-Za-z.]{1,10})\b", re.IGNORECASE)
_WATCH_RE = re.compile(r"\b(add|watch|remove|unwatch)\s+([A-Za-z.]{1,10})\b", re.IGNORECASE)


def _fmt_qty(quantity: float) -> str:
    return str(int(quantity)) if quantity == int(quantity) else str(quantity)


def mock_response(user_message: str) -> LLMResponse:
    trade = _TRADE_RE.search(user_message)
    if trade:
        side = trade.group(1).lower()
        quantity = float(trade.group(2))
        ticker = trade.group(3).upper()
        verb = "buying" if side == "buy" else "selling"
        return LLMResponse(
            message=f"Mock: {verb} {_fmt_qty(quantity)} {ticker}.",
            trades=[TradeAction(ticker=ticker, side=side, quantity=quantity)],
        )

    watch = _WATCH_RE.search(user_message)
    if watch:
        action = "add" if watch.group(1).lower() in ("add", "watch") else "remove"
        ticker = watch.group(2).upper()
        message = (
            f"Mock: adding {ticker} to your watchlist."
            if action == "add"
            else f"Mock: removing {ticker} from your watchlist."
        )
        return LLMResponse(
            message=message,
            watchlist_changes=[WatchlistChange(ticker=ticker, action=action)],
        )

    return LLMResponse(message=DEFAULT_MESSAGE)
