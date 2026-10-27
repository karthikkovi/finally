"""Structured-output parsing: valid shapes, malformed and partial responses."""

import json

from app.llm.models import LLMResponse
from app.llm.parsing import FALLBACK_MESSAGE, parse_llm_response


def test_message_only():
    r = parse_llm_response('{"message": "Hello"}')
    assert r == LLMResponse(message="Hello", trades=[], watchlist_changes=[])


def test_full_shape():
    payload = {
        "message": "Done",
        "trades": [
            {"ticker": "AAPL", "side": "buy", "quantity": 10},
            {"ticker": "TSLA", "side": "sell", "quantity": 0.5},
        ],
        "watchlist_changes": [
            {"ticker": "PYPL", "action": "add"},
            {"ticker": "NFLX", "action": "remove"},
        ],
    }
    r = parse_llm_response(json.dumps(payload))
    assert r.message == "Done"
    assert [(t.ticker, t.side, t.quantity) for t in r.trades] == [
        ("AAPL", "buy", 10.0),
        ("TSLA", "sell", 0.5),
    ]
    assert [(c.ticker, c.action) for c in r.watchlist_changes] == [
        ("PYPL", "add"),
        ("NFLX", "remove"),
    ]


def test_empty_arrays_and_trades_only():
    r = parse_llm_response(
        '{"message": "ok", "trades": [{"ticker": "MSFT", "side": "buy", "quantity": 1}],'
        ' "watchlist_changes": []}'
    )
    assert len(r.trades) == 1 and r.watchlist_changes == []


def test_empty_or_none_content_falls_back():
    assert parse_llm_response(None).message == FALLBACK_MESSAGE
    assert parse_llm_response("   ").message == FALLBACK_MESSAGE


def test_plain_text_is_shown_without_actions():
    r = parse_llm_response("Sure, your portfolio looks fine.")
    assert r.message == "Sure, your portfolio looks fine."
    assert r.trades == [] and r.watchlist_changes == []


def test_code_fenced_json():
    r = parse_llm_response('```json\n{"message": "fenced", "trades": []}\n```')
    assert r.message == "fenced"


def test_json_embedded_in_text():
    r = parse_llm_response('Here you go: {"message": "inner"} thanks')
    assert r.message == "inner"


def test_invalid_actions_dropped_valid_kept():
    payload = {
        "message": "mixed",
        "trades": [
            {"ticker": "AAPL", "side": "hold", "quantity": 1},
            {"ticker": "GOOGL", "side": "buy"},
            {"ticker": "NVDA", "side": "buy", "quantity": 2},
        ],
        "watchlist_changes": [{"ticker": "X", "action": "toggle"}, "junk"],
    }
    r = parse_llm_response(json.dumps(payload))
    assert r.message == "mixed"
    assert [t.ticker for t in r.trades] == ["NVDA"]
    assert r.watchlist_changes == []


def test_missing_message_falls_back_and_keeps_actions():
    r = parse_llm_response('{"trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1}]}')
    assert r.message == FALLBACK_MESSAGE
    assert len(r.trades) == 1


def test_non_list_actions_ignored():
    r = parse_llm_response('{"message": "x", "trades": "none", "watchlist_changes": null}')
    assert r.trades == [] and r.watchlist_changes == []


def test_truncated_json_falls_back_to_raw_text():
    raw = '{"message": "cut off'
    r = parse_llm_response(raw)
    assert r.message == raw
    assert r.trades == []


def test_json_array_is_not_accepted():
    r = parse_llm_response("[1, 2, 3]")
    assert r.trades == [] and r.watchlist_changes == []
