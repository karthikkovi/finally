"""LLM chat assistant: structured outputs, mock mode, action execution."""

from .chat import handle_chat, is_mock_mode
from .mock import mock_response
from .models import LLMResponse, TradeAction, WatchlistChange
from .parsing import parse_llm_response

__all__ = [
    "LLMResponse",
    "TradeAction",
    "WatchlistChange",
    "handle_chat",
    "is_mock_mode",
    "mock_response",
    "parse_llm_response",
]
