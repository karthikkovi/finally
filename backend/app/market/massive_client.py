"""Massive (formerly Polygon.io) REST poller implementing MarketDataSource."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """Polls the Massive snapshot endpoint for all active tickers in one call per interval.

    Free tier allows 5 req/min, hence the 15 s default interval.
    """

    def __init__(self, api_key: str, price_cache: PriceCache, poll_interval: float = 15.0) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(dict.fromkeys(tickers))
        await self._poll_once()
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._client = None

    async def add_ticker(self, ticker: str) -> None:
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            # Fetch right away so the new ticker isn't priceless for a whole interval
            await self._poll_once([ticker])

    async def remove_ticker(self, ticker: str) -> None:
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self, tickers: list[str] | None = None) -> None:
        tickers = tickers if tickers is not None else list(self._tickers)
        if not tickers or self._client is None:
            return
        try:
            snapshots = await asyncio.to_thread(
                self._client.get_snapshot_all,
                market_type=SnapshotMarketType.STOCKS,
                tickers=tickers,
            )
        except Exception as exc:  # network, auth, rate limit — keep polling
            logger.error("Massive poll failed: %s", exc)
            return
        self._process_snapshots(snapshots)

    def _process_snapshots(self, snapshots) -> None:
        active = set(self._tickers)
        for snap in snapshots or []:
            try:
                ticker = snap.ticker
                if ticker not in active:
                    continue
                price = float(snap.last_trade.price)
                ts_ms = snap.last_trade.timestamp
                timestamp = ts_ms / 1000 if ts_ms else None
                self._cache.update(ticker, price, timestamp=timestamp)
            except (AttributeError, TypeError, ValueError) as exc:
                ticker = getattr(snap, "ticker", "?")
                logger.warning("Skipping malformed snapshot %r: %s", ticker, exc)
