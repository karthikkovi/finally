"""SSE endpoint streaming the PriceCache to browsers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

STREAM_INTERVAL = 0.5


def format_sse(cache: PriceCache) -> str:
    """Serialize every tracked ticker into one SSE ``data:`` event."""
    payload = {ticker: update.to_dict() for ticker, update in cache.get_all().items()}
    return f"data: {json.dumps(payload)}\n\n"


async def _generate_events(
    cache: PriceCache, request: Request, interval: float = STREAM_INTERVAL
) -> AsyncGenerator[str, None]:
    yield "retry: 1000\n\n"
    last_version = -1
    while True:
        if await request.is_disconnected():
            break
        version = cache.version
        if version != last_version:
            last_version = version
            yield format_sse(cache)
        await asyncio.sleep(interval)


def create_stream_router(cache: PriceCache) -> APIRouter:
    router = APIRouter(prefix="/api/stream", tags=["stream"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _generate_events(cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router
