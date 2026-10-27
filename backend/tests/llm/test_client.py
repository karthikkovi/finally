"""LiteLLM call wrapper — litellm.completion is always mocked (no network)."""

from types import SimpleNamespace

from app.llm import client
from app.llm.models import LLMResponse


def _fake_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_call_llm_passes_cerebras_settings(monkeypatch):
    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return _fake_response('{"message": "hi", "trades": [], "watchlist_changes": []}')

    monkeypatch.setattr(client, "completion", fake_completion)
    result = client.call_llm([{"role": "user", "content": "hi"}])

    assert result.message == "hi"
    assert captured["model"] == "openrouter/openai/gpt-oss-120b"
    assert captured["extra_body"] == {"provider": {"order": ["cerebras"]}}
    assert captured["response_format"] is LLMResponse
    assert captured["reasoning_effort"] == "low"


def test_call_llm_network_error_returns_friendly_message(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(client, "completion", boom)
    result = client.call_llm([])
    assert result.message == client.UNAVAILABLE_MESSAGE
    assert result.trades == []


def test_call_llm_malformed_content(monkeypatch):
    monkeypatch.setattr(client, "completion", lambda **kw: _fake_response("not json at all"))
    result = client.call_llm([])
    assert result.message == "not json at all"
    assert result.trades == []
