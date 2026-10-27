"""Structured-output schema for the FinAlly chat assistant."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TradeAction(BaseModel):
    """A market order the assistant wants to execute."""

    ticker: str = Field(description="Ticker symbol, e.g. AAPL")
    side: Literal["buy", "sell"]
    quantity: float = Field(description="Number of shares (fractional allowed), must be > 0")


class WatchlistChange(BaseModel):
    """A watchlist modification the assistant wants to apply."""

    ticker: str = Field(description="Ticker symbol, e.g. PYPL")
    action: Literal["add", "remove"]


class LLMResponse(BaseModel):
    """The JSON object the LLM must return."""

    message: str = Field(description="Conversational response shown to the user")
    trades: list[TradeAction] = Field(default_factory=list)
    watchlist_changes: list[WatchlistChange] = Field(default_factory=list)
