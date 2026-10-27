"""SSE formatting and event generator."""

import json

from app.market import PriceCache, create_stream_router
from app.market.stream import _generate_events, format_sse


class FakeRequest:
    def __init__(self, disconnect_after: int):
        self.calls = 0
        self.disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > self.disconnect_after


def parse(event: str) -> dict:
    assert event.startswith("data: ") and event.endswith("\n\n")
    return json.loads(event[len("data: ") :])


def test_format_sse_contains_all_tickers():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("AAPL", 191.0)
    cache.update("MSFT", 420.0)
    payload = parse(format_sse(cache))
    assert set(payload) == {"AAPL", "MSFT"}
    assert payload["AAPL"]["price"] == 191.0
    assert payload["AAPL"]["previous_price"] == 190.0
    assert payload["AAPL"]["direction"] == "up"
    assert set(payload["AAPL"]) >= {"timestamp", "change", "change_percent", "open_price"}
    assert "change_percent_open" in payload["AAPL"]


def test_format_sse_empty_cache():
    assert parse(format_sse(PriceCache())) == {}


async def test_generator_sends_retry_then_data_only_on_change():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = [e async for e in _generate_events(cache, FakeRequest(3), interval=0)]
    assert events[0] == "retry: 1000\n\n"
    # 3 loop iterations, cache unchanged after the first → exactly one data event
    assert len(events) == 2
    assert parse(events[1])["AAPL"]["price"] == 190.0


async def test_generator_emits_on_each_change():
    cache = PriceCache()
    request = FakeRequest(3)
    gen = _generate_events(cache, request, interval=0)
    assert await gen.__anext__() == "retry: 1000\n\n"
    cache.update("AAPL", 1.0)
    assert parse(await gen.__anext__())["AAPL"]["price"] == 1.0
    cache.update("AAPL", 2.0)
    assert parse(await gen.__anext__())["AAPL"]["price"] == 2.0
    await gen.aclose()


def test_router_path():
    router = create_stream_router(PriceCache())
    assert [r.path for r in router.routes] == ["/api/stream/prices"]
