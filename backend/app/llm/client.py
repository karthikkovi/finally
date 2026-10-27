"""LiteLLM call to OpenRouter (Cerebras provider) with structured outputs."""

from __future__ import annotations

import logging

from litellm import completion

from .models import LLMResponse
from .parsing import parse_llm_response

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-oss-120b"
EXTRA_BODY = {"provider": {"order": ["cerebras"]}}

UNAVAILABLE_MESSAGE = (
    "Sorry, I couldn't reach the AI service right now. No actions were taken — please try again."
)


def call_llm(messages: list[dict]) -> LLMResponse:
    """Call the LLM and return a parsed response. Never raises."""
    try:
        response = completion(
            model=MODEL,
            messages=messages,
            response_format=LLMResponse,
            reasoning_effort="low",
            extra_body=EXTRA_BODY,
        )
        content = response.choices[0].message.content
    except Exception:
        logger.exception("LLM call failed")
        return LLMResponse(message=UNAVAILABLE_MESSAGE)
    return parse_llm_response(content)
