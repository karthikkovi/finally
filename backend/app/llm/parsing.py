"""Robust parsing of LLM output into an LLMResponse.

Strict validation is tried first. If that fails, we salvage what we can: extract the
outermost JSON object, keep a usable message, and keep only the individual actions
that validate. Parsing never raises.
"""

from __future__ import annotations

import json
import logging
import re

from pydantic import ValidationError

from .models import LLMResponse, TradeAction, WatchlistChange

logger = logging.getLogger(__name__)

FALLBACK_MESSAGE = (
    "Sorry, I had trouble understanding the AI response. No actions were taken — please try again."
)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _extract_json_object(text: str) -> dict | None:
    text = _FENCE_RE.sub("", text.strip())
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, TypeError):
        pass
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _valid_items(raw, model) -> list:
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw:
        try:
            items.append(model.model_validate(entry))
        except ValidationError:
            logger.warning("Dropping invalid %s from LLM output: %r", model.__name__, entry)
    return items


def parse_llm_response(content: str | None) -> LLMResponse:
    """Parse raw LLM content into an LLMResponse; never raises."""
    if not content or not content.strip():
        return LLMResponse(message=FALLBACK_MESSAGE)

    try:
        return LLMResponse.model_validate_json(content)
    except ValidationError:
        pass

    data = _extract_json_object(content)
    if data is None:
        # Plain text answer with no JSON: show it, take no actions.
        logger.warning("LLM returned non-JSON content")
        return LLMResponse(message=content.strip())

    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        message = FALLBACK_MESSAGE
    return LLMResponse(
        message=message,
        trades=_valid_items(data.get("trades"), TradeAction),
        watchlist_changes=_valid_items(data.get("watchlist_changes"), WatchlistChange),
    )
