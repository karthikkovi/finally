"""FastAPI application: API routes, SSE stream, background tasks, and static frontend."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from app import db
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.routes import chat, health, portfolio, watchlist
from app.services import record_snapshot, tracked_tickers

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

load_dotenv(REPO_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("app")

SNAPSHOT_INTERVAL = float(os.environ.get("SNAPSHOT_INTERVAL", "30"))


async def _snapshot_loop(cache: PriceCache, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            await asyncio.to_thread(record_snapshot, cache)
        except Exception:
            logger.exception("Portfolio snapshot failed")


price_cache = PriceCache()


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    source = create_market_data_source(price_cache)
    app.state.price_cache = price_cache
    app.state.market_source = source
    await source.start(tracked_tickers())
    record_snapshot(price_cache)
    snapshot_task = asyncio.create_task(_snapshot_loop(price_cache, SNAPSHOT_INTERVAL))
    try:
        yield
    finally:
        snapshot_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await snapshot_task
        await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.state.price_cache = price_cache

app.include_router(health.router)
app.include_router(portfolio.router)
app.include_router(watchlist.router)
app.include_router(create_stream_router(price_cache))

app.include_router(chat.router)


def _mount_static(app: FastAPI, static_dir: Path) -> None:
    """Serve the Next.js static export at / with index.html fallback for client routes."""
    root = static_dir.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if candidate.is_relative_to(root):
            if candidate.is_file():
                return FileResponse(candidate)
            if candidate.is_dir() and (candidate / "index.html").is_file():
                return FileResponse(candidate / "index.html")
            html = candidate.with_name(candidate.name + ".html")
            if path and html.is_file():
                return FileResponse(html)
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="Not Found")


STATIC_DIR = Path(os.environ.get("STATIC_DIR", BACKEND_DIR / "static"))
if STATIC_DIR.is_dir():
    _mount_static(app, STATIC_DIR)
else:
    logger.info("Static dir %s not found; serving API only", STATIC_DIR)
