"""GBM price simulator with correlated moves and random shock events."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import random

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    SEED_PRICES,
    TICKER_PARAMS,
)

logger = logging.getLogger(__name__)

# 500ms as a fraction of a trading year (252 days x 6.5 hours)
DEFAULT_DT = 0.5 / (252 * 6.5 * 3600)


class GBMSimulator:
    """Generates correlated Geometric Brownian Motion price paths for multiple tickers.

    S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)
    with Z drawn from a Cholesky-correlated multivariate normal.
    """

    def __init__(
        self,
        tickers: list[str] | None = None,
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
        seed: int | None = None,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._rng = np.random.default_rng(seed)
        self._random = random.Random(seed)
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None
        for ticker in tickers or []:
            self._add(ticker)
        self._rebuild_cholesky()

    def _add(self, ticker: str) -> bool:
        if ticker in self._prices:
            return False
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, round(self._random.uniform(50, 300), 2))
        self._params[ticker] = TICKER_PARAMS.get(ticker, DEFAULT_PARAMS)
        return True

    def add_ticker(self, ticker: str) -> None:
        if self._add(ticker):
            self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    def get_price(self, ticker: str) -> float | None:
        price = self._prices.get(ticker)
        return round(price, 2) if price is not None else None

    def step(self) -> dict[str, float]:
        """Advance one time step and return ``{ticker: new_price}`` rounded to cents."""
        n = len(self._tickers)
        if n == 0:
            return {}

        z = self._rng.standard_normal(n)
        if self._cholesky is not None:
            z = self._cholesky @ z

        sqrt_dt = math.sqrt(self._dt)
        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            mu = self._params[ticker]["mu"]
            sigma = self._params[ticker]["sigma"]
            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * sqrt_dt * z[i]
            price = self._prices[ticker] * math.exp(drift + diffusion)

            if self._random.random() < self._event_prob:
                shock = self._random.uniform(0.02, 0.05) * self._random.choice([-1, 1])
                price *= 1 + shock
                logger.debug("Random event on %s: %+.2f%%", ticker, shock * 100)

            self._prices[ticker] = price
            result[ticker] = round(price, 2)
        return result

    def _rebuild_cholesky(self) -> None:
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self.correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def correlation(t1: str, t2: str) -> float:
        """Pairwise correlation: same sector is higher, everything else uses the baseline."""
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR


class SimulatorDataSource(MarketDataSource):
    """Runs a GBMSimulator in a background asyncio task, writing to the PriceCache."""

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(tickers=list(tickers), event_probability=self._event_prob)
        # Seed the cache immediately so prices are available before the first tick
        for ticker in self._sim.get_tickers():
            self._cache.update(ticker, self._sim.get_price(ticker))
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def add_ticker(self, ticker: str) -> None:
        if self._sim is None:
            self._sim = GBMSimulator(event_probability=self._event_prob)
        if ticker in self._sim.get_tickers():
            return
        self._sim.add_ticker(ticker)
        self._cache.update(ticker, self._sim.get_price(ticker))

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim is not None:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim is not None:
                    for ticker, price in self._sim.step().items():
                        self._cache.update(ticker, price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
