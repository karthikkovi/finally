# Market Data Backend — Detailed Design

**Scope:** everything under `backend/app/market/` — the unified data-source interface, the shared price cache, the GBM simulator, the Massive (Polygon.io) REST poller, the SSE stream, and how the rest of the backend (watchlist, trades, portfolio, chat) plugs into it.

**Status:** The core of this design is already implemented and tested (73 tests, see `MARKET_DATA_SUMMARY.md`). This document is the canonical spec for that code *and* for the remaining work. Sections marked **🔧 Change** describe deltas from the current code — gaps found while re-reading it against `PLAN.md`. Everything else matches the code as it stands. It supersedes `archive/MARKET_DATA_DESIGN.md`, `archive/MARKET_INTERFACE.md`, and `archive/MARKET_SIMULATOR.md`.

---

## Table of Contents

1. [Requirements](#1-requirements)
2. [Architecture](#2-architecture)
3. [Module Layout](#3-module-layout)
4. [Data Model — `PriceUpdate`](#4-data-model--priceupdate)
5. [Price Cache — `PriceCache`](#5-price-cache--pricecache)
6. [Unified Interface — `MarketDataSource`](#6-unified-interface--marketdatasource)
7. [Seed Prices & Parameters](#7-seed-prices--parameters)
8. [Simulator](#8-simulator)
9. [Massive API Client](#9-massive-api-client)
10. [Factory](#10-factory)
11. [SSE Streaming](#11-sse-streaming)
12. [FastAPI Integration](#12-fastapi-integration)
13. [Error Handling & Edge Cases](#13-error-handling--edge-cases)
14. [Configuration](#14-configuration)
15. [Testing](#15-testing)
16. [Implementation Checklist](#16-implementation-checklist)

---

## 1. Requirements

Traced from `PLAN.md` §6, §8, §10:

| # | Requirement | Where it is met |
|---|---|---|
| R1 | One interface, two implementations; downstream code is source-agnostic | `MarketDataSource` ABC (§6) |
| R2 | Simulator by default; Massive when `MASSIVE_API_KEY` is non-empty | `create_market_data_source()` (§10) |
| R3 | Simulator: GBM, ~500 ms ticks, correlated moves, random 2–5% events, realistic seeds | `GBMSimulator` (§8) |
| R4 | Massive: REST polling (not WebSocket), all tickers in one call, 15 s on free tier | `MassiveDataSource` (§9) |
| R5 | Shared in-memory cache: latest price, previous price, timestamp per ticker | `PriceCache` (§5) |
| R6 | `GET /api/stream/prices` SSE, ~500 ms cadence, ticker/price/previous/timestamp/direction | `create_stream_router()` (§11) |
| R7 | Watchlist add/remove changes the tracked set at runtime | `add_ticker` / `remove_ticker` (§6, §12.4) |
| R8 | Trades fill instantly at the current price | `PriceCache.get_price()` (§12.5) |
| R9 | Watchlist shows **daily change %** | `PriceUpdate.day_change_percent` (§4, 🔧 Change) |

---

## 2. Architecture

```
                    ┌──────────────────────────────────────┐
  MASSIVE_API_KEY ─▶│ create_market_data_source(cache)     │
                    └───────────────┬──────────────────────┘
                                    │ returns one of
             ┌──────────────────────┴───────────────────────┐
             ▼                                              ▼
  ┌─────────────────────────┐                ┌────────────────────────────┐
  │ SimulatorDataSource     │                │ MassiveDataSource          │
  │  asyncio task, 500 ms   │                │  asyncio task, 15 s        │
  │  GBMSimulator.step()    │                │  to_thread(get_snapshot_all)│
  └────────────┬────────────┘                └─────────────┬──────────────┘
               │ cache.update(ticker, price, ...)          │
               └──────────────────────┬────────────────────┘
                                      ▼
                       ┌──────────────────────────────┐
                       │ PriceCache  (Lock, version)  │  ← single source of truth
                       └──┬───────────┬───────────┬───┘
                          │           │           │
            get_all()+version   get_price()   get_all()
                          ▼           ▼           ▼
                 SSE /api/stream   POST trade   GET portfolio / watchlist,
                 /prices (500 ms)                chat context, snapshots
```

**Principles**

- **Producers push, consumers pull.** A data source never returns prices to a caller; it writes into the `PriceCache` on its own schedule. Every consumer reads the cache. This decouples the tick rate (500 ms simulator vs 15 s Massive) from the SSE cadence and from request handling.
- **Exactly one producer per process.** The factory picks one source at startup; it is never swapped at runtime.
- **The cache holds only the latest value per ticker.** Memory is O(tickers). History (sparklines, the main chart) is accumulated on the frontend from the SSE stream, as `PLAN.md` specifies. Portfolio history is a separate DB table (`portfolio_snapshots`) owned by the portfolio module.

**Concurrency model**

| Actor | Runs on | Touches |
|---|---|---|
| Simulator loop | event loop (asyncio task) | `GBMSimulator` state, `cache.update` |
| Massive loop | event loop; HTTP call in a worker thread via `asyncio.to_thread` | `cache.update` (from the loop, after the thread returns) |
| SSE generators (one per client) | event loop | `cache.version`, `cache.get_all` |
| Route handlers | event loop | `cache.get*`, `source.add_ticker/remove_ticker` |

All cache mutation happens on the event loop today, but `PriceCache` uses a `threading.Lock` anyway so it stays correct if a producer ever writes from a thread (and on free-threaded Python builds). `GBMSimulator` is *not* thread-safe and is only touched from the event loop.

---

## 3. Module Layout

```
backend/
├── app/
│   └── market/
│       ├── __init__.py        # Public exports
│       ├── models.py          # PriceUpdate (frozen dataclass)
│       ├── cache.py           # PriceCache
│       ├── interface.py       # MarketDataSource ABC
│       ├── seed_prices.py     # SEED_PRICES, TICKER_PARAMS, correlation constants
│       ├── simulator.py       # GBMSimulator + SimulatorDataSource
│       ├── massive_client.py  # MassiveDataSource
│       ├── factory.py         # create_market_data_source()
│       └── stream.py          # create_stream_router() — SSE endpoint
├── tests/market/              # pytest suite (one file per module)
└── market_data_demo.py        # Rich terminal demo
```

Public API (`app/market/__init__.py`) — downstream code imports only these:

```python
from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
]
```

Dependencies (`backend/pyproject.toml`): `fastapi`, `uvicorn[standard]`, `numpy` (Cholesky + normal draws), `massive` (Polygon.io client; a core dependency so imports are top-level and tests can patch it). Dev: `pytest`, `pytest-asyncio` (`asyncio_mode = "auto"`), `pytest-cov`, `ruff`, plus **`httpx`** for the SSE/route tests in §15 (🔧 add).

---

## 4. Data Model — `PriceUpdate`

The only type that leaves the market layer. Immutable, hashable, cheap (`slots=True`). Derived values are properties so they can never disagree with the stored fields.

```python
# app/market/models.py
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    # 🔧 Change: reference price for "daily change %" (PLAN §10).
    # Simulator: first price of the session. Massive: previous day's close.
    session_open: float | None = None

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat' — drives the green/red flash on the frontend."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change(self) -> float:
        """Absolute change vs. session open / previous close."""
        if not self.session_open:
            return 0.0
        return round(self.price - self.session_open, 4)

    @property
    def day_change_percent(self) -> float:
        """Percentage change vs. session open / previous close."""
        if not self.session_open:
            return 0.0
        return round((self.price - self.session_open) / self.session_open * 100, 4)

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
            "day_change": self.day_change,
            "day_change_percent": self.day_change_percent,
        }
```

**Why `session_open` (🔧 Change):** `change_percent` is tick-over-tick — useful for the flash but meaningless as a "daily change %" (it is ~0.01% on every simulator tick and 0% on most Massive polls). The watchlist needs a stable reference. Adding it as a defaulted trailing field keeps every existing constructor call and test valid.

**Example**

```python
>>> u = PriceUpdate("AAPL", price=191.20, previous_price=191.05,
...                 timestamp=1761134400.0, session_open=190.00)
>>> u.direction, u.change, u.day_change_percent
('up', 0.15, 0.6316)
>>> u.to_dict()["day_change_percent"]
0.6316
```

---

## 5. Price Cache — `PriceCache`

```python
# app/market/cache.py
from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; bumped on every update

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        session_open: float | None = None,
    ) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        If this is the first update for the ticker, previous_price == price
        (direction='flat'). session_open, if not given, is carried forward from
        the previous update, or set to this price on the first update.
        """
        with self._lock:
            ts = time.time() if timestamp is None else timestamp  # 🔧 was `timestamp or ...`
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price
            if session_open is None:
                session_open = prev.session_open if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
                session_open=round(session_open, 2),
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices (shallow copy — values are immutable)."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1  # 🔧 so SSE clients see the removal promptly

    @property
    def version(self) -> int:
        with self._lock:  # 🔧 read under lock (no-GIL safety; review item 3.4)
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

**Version counter.** SSE generators remember the last version they sent and skip a cycle when nothing changed. With Massive polling every 15 s, this means ~29 of every 30 SSE cycles send nothing instead of re-sending identical data. Bumping on `remove()` makes a removed ticker disappear from the next SSE frame instead of lingering until the next price write.

**Rounding.** Prices are stored rounded to cents; the simulator keeps full precision internally (§8), so rounding never compounds.

**Usage**

```python
cache = PriceCache()
cache.update("AAPL", 190.00)                 # first: flat, session_open=190.00
u = cache.update("AAPL", 190.37)             # up, change=0.37, day_change_percent=0.1947
cache.get_price("AAPL")                      # 190.37
"AAPL" in cache, len(cache)                  # (True, 1)
cache.update("AAPL", 191.0, session_open=188.5)  # Massive passes prev close explicitly
```

---

## 6. Unified Interface — `MarketDataSource`

```python
# app/market/interface.py
from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source directly for prices —
    it reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        await source.add_ticker("TSLA")
        await source.remove_ticker("GOOGL")
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates. Called exactly once."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel the background task. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set and from the PriceCache. No-op if absent."""

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

### Behavioural contract (both implementations must satisfy; enforce with a shared parametrized test)

| Operation | Contract |
|---|---|
| `start(tickers)` | Returns once the cache holds a first value for every *priceable* ticker (simulator: seed prices; Massive: result of an immediate first poll). Spawns one named asyncio task. |
| `stop()` | Cancels and awaits the task; swallows `CancelledError`; safe to call twice or before `start`. Never writes to the cache afterwards. |
| `add_ticker(t)` | Idempotent. Simulator: priced immediately. Massive: priced on the next poll (≤ interval). |
| `remove_ticker(t)` | Idempotent. Removes `t` from the cache **and** guarantees no later write re-adds it (see §9.4). |
| `get_tickers()` | Returns a copy; insertion order. |
| Ticker format | Callers pass upper-case, stripped symbols. Normalization is done once at the API boundary (§12.4); sources also normalize defensively (🔧 the simulator currently does not). |

---

## 7. Seed Prices & Parameters

```python
# app/market/seed_prices.py
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00, "GOOGL": 175.00, "MSFT": 420.00, "AMZN": 185.00, "TSLA": 250.00,
    "NVDA": 800.00, "META": 500.00, "JPM": 195.00, "V": 280.00, "NFLX": 600.00,
}

# sigma: annualized volatility; mu: annualized drift
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT": {"sigma": 0.20, "mu": 0.05},
    "AMZN": {"sigma": 0.28, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # High volatility
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "META": {"sigma": 0.30, "mu": 0.05},
    "JPM": {"sigma": 0.18, "mu": 0.04},   # Low volatility (bank)
    "V": {"sigma": 0.17, "mu": 0.04},     # Low volatility (payments)
    "NFLX": {"sigma": 0.35, "mu": 0.05},
}
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}
INTRA_TECH_CORR = 0.6
INTRA_FINANCE_CORR = 0.5
CROSS_GROUP_CORR = 0.3   # between sectors and for unknown tickers
TSLA_CORR = 0.3          # TSLA does its own thing
```

**Unknown tickers** (added via watchlist/chat, e.g. `PYPL`) get `DEFAULT_PARAMS` and a seed price.

🔧 **Change — deterministic unknown seeds.** Today an unknown ticker gets `random.uniform(50, 300)`, so removing and re-adding `PYPL` (or restarting the container while holding a `PYPL` position) teleports its price — a held position's P&L jumps by up to ±80%. Derive the seed from the symbol instead, so it is stable across restarts:

```python
import hashlib

def seed_price_for(ticker: str) -> float:
    """Known seed, else a stable pseudo-random price in [50, 300) derived from the symbol."""
    if ticker in SEED_PRICES:
        return SEED_PRICES[ticker]
    h = int.from_bytes(hashlib.sha256(ticker.encode()).digest()[:4], "big")
    return round(50.0 + (h / 2**32) * 250.0, 2)
```

For held positions after a restart, the integration layer goes one step further and seeds from the position's last known price (§12.3).

---

## 8. Simulator

### 8.1 Math

Geometric Brownian Motion, exact discretization:

```
S(t+dt) = S(t) · exp( (μ − σ²/2)·dt + σ·√dt·Z )
```

- `dt` is the tick length as a fraction of a trading year: `0.5 s / (252 · 6.5 · 3600 s) ≈ 8.48e-8`.
- Per-tick log-return std-dev is `σ·√dt`: AAPL `0.22·2.91e-4 ≈ 0.0064%` (~1.2¢ on $190); TSLA `0.50·2.91e-4 ≈ 0.0146%` (~3.6¢ on $250). Every tick moves visibly at 2-decimal precision, so the flash animation fires constantly — the intended "alive" feel.
- Over one simulated trading day (46,800 ticks) the daily std-dev is σ/√252: AAPL ≈ 1.4%, TSLA ≈ 3.1% — realistic intraday ranges.
- `exp()` is always positive, so prices can never go ≤ 0 from diffusion.

**Correlation.** Build an n×n correlation matrix `C` from sector rules, factor it once `C = L·Lᵀ` (Cholesky), then each tick draw `z ~ N(0, I)` and use `L·z`, which has covariance `C`. All off-diagonals are in {0.3, 0.5, 0.6} with a block structure, so `C` is positive-definite for any ticker mix and Cholesky never fails. Rebuild is O(n³) but only on add/remove with n < 50.

**Events.** Each tick, each ticker has probability `p = 0.001` of a shock `×(1 ± U(0.02, 0.05))`. Expected rate: 10 tickers × 2 ticks/s × 0.001 = one event every ~50 s across the board. Shocks are multiplicative and < 5%, so they cannot drive a price negative.

### 8.2 `GBMSimulator` — pure, synchronous, deterministic under a seed

```python
# app/market/simulator.py (math engine)
class GBMSimulator:
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600  # 5,896,800
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
        initial_prices: dict[str, float] | None = None,   # 🔧 see §12.3
        rng: np.random.Generator | None = None,           # 🔧 deterministic tests
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability
        self._rng = rng or np.random.default_rng()
        self._initial = initial_prices or {}
        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None
        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def step(self) -> dict[str, float]:
        """Advance all tickers one tick. Hot path — called every 500 ms."""
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
            self._prices[ticker] *= math.exp(drift + diffusion)

            if self._rng.random() < self._event_prob:
                shock = self._rng.uniform(0.02, 0.05) * self._rng.choice([-1, 1])
                self._prices[ticker] *= 1 + shock
                logger.debug("Random event on %s: %+.1f%%", ticker, shock * 100)

            result[ticker] = round(self._prices[ticker], 2)  # full precision kept internally
        return result

    def add_ticker(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    def _add_ticker_internal(self, ticker: str) -> None:
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = self._initial.get(ticker) or seed_price_for(ticker)
        self._params[ticker] = dict(TICKER_PARAMS.get(ticker, DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return
        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = corr[j, i] = rho
        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        tech, finance = CORRELATION_GROUPS["tech"], CORRELATION_GROUPS["finance"]
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR
        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR
        return CROSS_GROUP_CORR
```

🔧 **Change — injectable RNG.** The current code uses the global `np.random` and `random` modules. Routing all randomness through one `np.random.Generator` lets tests pass `np.random.default_rng(42)` and assert exact paths, and avoids cross-test interference.

**Example**

```python
>>> sim = GBMSimulator(["AAPL", "NVDA", "JPM"], rng=np.random.default_rng(42))
>>> sim.step()
{'AAPL': 190.0, 'NVDA': 800.01, 'JPM': 194.99}   # illustrative
>>> sim.add_ticker("PYPL"); sim.get_tickers()
['AAPL', 'NVDA', 'JPM', 'PYPL']
```

### 8.3 `SimulatorDataSource` — async wrapper

```python
class SimulatorDataSource(MarketDataSource):
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

    async def start(self, tickers: list[str], initial_prices: dict[str, float] | None = None) -> None:
        tickers = [t.upper().strip() for t in tickers]
        self._sim = GBMSimulator(
            tickers=tickers, event_probability=self._event_prob, initial_prices=initial_prices
        )
        # Seed the cache so the first SSE frame and any immediate trade have a price.
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None and ticker not in self._cache:
                self._cache.update(ticker=ticker, price=price)  # priced immediately

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        while True:
            try:
                if self._sim:
                    for ticker, price in self._sim.step().items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")  # never let the loop die
            await asyncio.sleep(self._interval)
```

Notes:
- `step()` and the cache writes run in one synchronous block with no `await`, so an `add/remove_ticker` can never interleave mid-tick: a removed ticker is never re-written.
- Extra `initial_prices` kwarg on `start` is simulator-specific; the integration layer calls it via the factory helper in §12.3 so the ABC signature is unchanged.
- The `ticker not in self._cache` guard in `add_ticker` avoids resetting `previous_price` for a ticker already being priced.

---

## 9. Massive API Client

### 9.1 Endpoint

One call fetches every watched ticker — critical for the free tier's 5 req/min.

```
GET https://api.massive.com/v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,GOOGL,MSFT
Authorization: Bearer <MASSIVE_API_KEY>
```

```python
from massive import RESTClient
from massive.rest.models import SnapshotMarketType

client = RESTClient(api_key=api_key)
snapshots = client.get_snapshot_all(
    market_type=SnapshotMarketType.STOCKS,
    tickers=["AAPL", "GOOGL", "MSFT"],
)
```

### 9.2 Response → cache mapping

Abridged response element (the client returns `TickerSnapshot` objects with snake_case attributes):

```json
{
  "ticker": "AAPL",
  "todaysChange": -1.23, "todaysChangePerc": -0.64,
  "updated": 1761134399000000000,
  "day":     {"o": 191.2, "h": 192.0, "l": 189.5, "c": 190.1, "v": 41000000},
  "prevDay": {"o": 190.0, "h": 191.9, "l": 189.0, "c": 191.33, "v": 52000000},
  "min":     {"c": 190.08, "t": 1761134340000},
  "lastTrade": {"p": 190.10, "s": 100, "t": 1761134399000000000}
}
```

| Cache field | Source (first non-null wins) |
|---|---|
| `price` | `last_trade.price` → `min.close` → `day.close` → `prev_day.close` |
| `timestamp` | `last_trade.sip_timestamp` → `updated` → `min.timestamp` → `time.time()` (normalized, see below) |
| `session_open` | `prev_day.close` (so `day_change_percent` matches the broker's "today's change %") |

**🔧 Field names — verified against the installed `massive` package.** The client's `LastTrade` model has **no `timestamp` attribute**. Its fields are `price`, `size`, `exchange`, `sip_timestamp`, `participant_timestamp`, `trf_timestamp`, and others. `TickerSnapshot.from_dict` maps JSON `lastTrade.t` to `last_trade.sip_timestamp`. The current code reads `snap.last_trade.timestamp`, which raises `AttributeError` on every real snapshot. The per-snapshot `except (AttributeError, TypeError)` then skips it with a warning, so **Massive mode never writes a single price**. The existing tests don't catch this because they use `MagicMock` snapshots, which have every attribute. Verified with:

```python
>>> s = TickerSnapshot.from_dict({"ticker": "AAPL", "lastTrade": {"p": 190.1, "t": 1761134399000000000}})
>>> s.last_trade.sip_timestamp, s.last_trade.price
(1761134399000000000, 190.1)
>>> s.last_trade.timestamp
AttributeError: 'LastTrade' object has no attribute 'timestamp'
```

Other relevant fields: `snap.prev_day.close`, `snap.day.close`, `snap.min.close`, `snap.min.timestamp` (ms), `snap.updated` (ns), `snap.todays_change_percent`. Note that there is **no** `day.previous_close` or `day.change_percent`, despite what `archive/MASSIVE_API.md` says.

**Timestamp units.** `last_trade.sip_timestamp` and `updated` are nanoseconds; `min.timestamp` is milliseconds. The current code divides by 1000 unconditionally. 🔧 Normalize by magnitude so any unit works:

```python
def to_unix_seconds(ts: float | int | None) -> float:
    """Accept s / ms / µs / ns epoch timestamps; return float seconds."""
    if not ts:
        return time.time()
    ts = float(ts)
    for divisor in (1.0, 1e3, 1e6, 1e9):
        if ts / divisor < 1e11:      # < year ~5138 in seconds
            return ts / divisor
    return time.time()
```

**Market closed / pre-market.** `last_trade` still reflects the last print (possibly after-hours), so prices are frozen-but-valid outside trading hours. With the version counter, SSE simply stops emitting until something changes. `day` may be zeroed pre-market — the fallback chain skips zero/None values.

**Unknown symbols.** A ticker Massive doesn't recognize is silently absent from the response. It stays in the source's ticker list with no cache entry; the watchlist endpoint returns `price: null` for it and the trade endpoint rejects it (§12.5).

### 9.3 Rate limiting & errors

| Failure | Behaviour |
|---|---|
| 401 / 403 | Logged at ERROR once per streak; loop keeps running (fixing `.env` requires a restart anyway). |
| 429 | Exponential backoff: next sleep = `min(interval × 2^k, 120 s)`; reset on success. |
| Network / 5xx | The client retries internally; on final failure, same backoff. |
| Malformed snapshot | That ticker is skipped with a WARNING; others still update. |

Poll interval is configurable via `MASSIVE_POLL_INTERVAL` (default 15 s, the free-tier safe value; paid tiers can use 2–5 s).

### 9.4 Implementation

```python
# app/market/massive_client.py
from __future__ import annotations

import asyncio
import logging
import time

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)

MAX_BACKOFF_SECONDS = 120.0


def _first_positive(*values: float | None) -> float | None:
    for v in values:
        if v is not None and v > 0:
            return float(v)
    return None


def _attr(obj, *path):
    """Safe nested getattr: _attr(snap, 'last_trade', 'price') → value or None."""
    for name in path:
        obj = getattr(obj, name, None)
        if obj is None:
            return None
    return obj


class MassiveDataSource(MarketDataSource):
    """Polls the Massive snapshot endpoint for all tracked tickers in one call."""

    def __init__(self, api_key: str, price_cache: PriceCache, poll_interval: float = 15.0) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None
        self._failures = 0

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = [t.upper().strip() for t in tickers]
        await self._poll_once()  # cache populated before the app starts serving
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info("Massive poller started: %d tickers, %.1fs interval",
                    len(self._tickers), self._interval)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        if ticker not in self._tickers:
            self._tickers.append(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- internals ---

    def _next_delay(self) -> float:
        if self._failures == 0:
            return self._interval
        return min(self._interval * 2 ** self._failures, MAX_BACKOFF_SECONDS)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._next_delay())
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers or not self._client:
            return
        requested = list(self._tickers)  # 🔧 snapshot: the list may change while the thread runs
        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots, requested)
        except Exception as e:
            self._failures += 1
            logger.error("Massive poll failed (%d in a row): %s", self._failures, e)
            return
        self._failures = 0

        active = set(self._tickers)  # 🔧 re-read AFTER the await
        processed = 0
        for snap in snapshots:
            ticker = getattr(snap, "ticker", None)
            if ticker not in active:
                continue  # removed while the request was in flight — don't resurrect it
            price = _first_positive(
                _attr(snap, "last_trade", "price"),
                _attr(snap, "min", "close"),
                _attr(snap, "day", "close"),
                _attr(snap, "prev_day", "close"),
            )
            if price is None:
                logger.warning("Skipping snapshot for %s: no usable price", ticker)
                continue
            ts = to_unix_seconds(
                _attr(snap, "last_trade", "sip_timestamp")
                or getattr(snap, "updated", None)
                or _attr(snap, "min", "timestamp")
            )
            self._cache.update(
                ticker=ticker,
                price=price,
                timestamp=ts,
                session_open=_first_positive(_attr(snap, "prev_day", "close")),
            )
            processed += 1
        logger.debug("Massive poll: updated %d/%d tickers", processed, len(requested))

    def _fetch_snapshots(self, tickers: list[str]) -> list:
        """Synchronous HTTP call; runs in a worker thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=tickers,
        )
```

🔧 **Changes vs. current code, and why:**

0. **Read `last_trade.sip_timestamp`, not `last_trade.timestamp`.** This is the blocking bug from §9.2. Without the fix, Massive mode produces no prices at all. Add a test that builds snapshots with the real `TickerSnapshot.from_dict` instead of `MagicMock` (§15.3).
1. **Pass a copy of the ticker list to the thread** and **filter results against the live set after the await.** Without this, `remove_ticker("GOOGL")` during an in-flight request removes it from the cache, then the poll completes and writes it straight back — the ticker reappears on screen until the next restart.
2. **Price fallback chain** instead of only `last_trade.price` (which can be absent, e.g. on plans without trade data).
3. **`session_open = prev_day.close`** for a real daily change %.
4. **Timestamp normalization** (ns vs ms).
5. **Backoff on consecutive failures** so a bad key or 429 doesn't keep hammering the API at the base rate.

---

## 10. Factory

```python
# app/market/factory.py
def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """MASSIVE_API_KEY set and non-empty → MassiveDataSource, else SimulatorDataSource.

    Returns an unstarted source. Caller must `await source.start(tickers)`.
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15") or 15)
        logger.info("Market data source: Massive API (poll every %.1fs)", interval)
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)
    logger.info("Market data source: GBM Simulator")
    return SimulatorDataSource(price_cache=price_cache)
```

| `MASSIVE_API_KEY` | Result |
|---|---|
| unset | `SimulatorDataSource` |
| `""` or `"   "` | `SimulatorDataSource` |
| `"abc123"` | `MassiveDataSource(poll_interval=15.0)` |
| `"abc123"` + `MASSIVE_POLL_INTERVAL=5` | `MassiveDataSource(poll_interval=5.0)` |

---

## 11. SSE Streaming

### 11.1 Wire format

```
retry: 1000

data: {"AAPL":{"ticker":"AAPL","price":190.37,"previous_price":190.25,"timestamp":1761134400.51,"change":0.12,"change_percent":0.0631,"direction":"up","day_change":0.37,"day_change_percent":0.1947},"GOOGL":{...}}

: keepalive

data: {...}
```

- One `data:` frame = the **full** current price map (≤ ~50 tickers, a few KB). Full snapshots, not deltas, make reconnects trivial: the first frame after reconnect is complete state.
- A frame is sent only when `cache.version` changed since the last frame (checked every 500 ms).
- `retry: 1000` tells `EventSource` to reconnect 1 s after a drop.
- 🔧 **Keepalive comment** (`: keepalive\n\n`) every 15 s when nothing was sent. In Massive mode, idle stretches (market closed) otherwise produce no bytes for minutes and proxies/load balancers (App Runner, Render) kill the connection.

### 11.2 Implementation

```python
# app/market/stream.py
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

KEEPALIVE_SECONDS = 15.0


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    # 🔧 Router created per call (was module-level → duplicate routes if called twice, e.g. in tests)
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    yield "retry: 1000\n\n"
    last_version = -1
    last_sent = time.monotonic()
    client = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client)
    try:
        while not await request.is_disconnected():
            version = price_cache.version
            if version != last_version:
                last_version = version
                prices = price_cache.get_all()
                payload = {t: u.to_dict() for t, u in prices.items()}
                yield f"data: {json.dumps(payload)}\n\n"
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent >= KEEPALIVE_SECONDS:
                yield ": keepalive\n\n"
                last_sent = time.monotonic()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("SSE client disconnected: %s", client)
```

Note the current code skips the frame when the cache is empty; sending `data: {}` instead (as above) lets the frontend distinguish "connected, no tickers" from "not connected yet", which matters when the user removes every ticker.

### 11.3 Frontend consumer (reference for the Frontend Engineer)

```ts
// frontend: lib/usePriceStream.ts
export type PriceTick = {
  ticker: string; price: number; previous_price: number; timestamp: number;
  change: number; change_percent: number; direction: "up" | "down" | "flat";
  day_change: number; day_change_percent: number;
};
type Status = "connected" | "reconnecting" | "disconnected";

export function connectPrices(
  onPrices: (prices: Record<string, PriceTick>) => void,
  onStatus: (s: Status) => void,
): () => void {
  const es = new EventSource("/api/stream/prices");
  es.onopen = () => onStatus("connected");
  es.onmessage = (e) => onPrices(JSON.parse(e.data));
  es.onerror = () =>
    onStatus(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
  return () => es.close();
}
```

Sparklines: append `price` to a per-ticker ring buffer (e.g. last 300 points) only when `timestamp` differs from the last stored point — frames are full snapshots, so an unchanged ticker repeats its last value. Flash: apply the `up`/`down` class when `direction !== "flat"` and `timestamp` changed.

---

## 12. FastAPI Integration

### 12.1 Lifespan

```python
# app/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import get_tracked_tickers, init_db   # owned by the backend/DB agent
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.market.startup import start_source


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()                                     # lazy schema + seed (PLAN §7)
    cache = PriceCache()
    source = create_market_data_source(cache)
    await start_source(source)                    # §12.3
    app.state.price_cache = cache
    app.state.market_source = source
    app.include_router(create_stream_router(cache))
    try:
        yield
    finally:
        await source.stop()


app = FastAPI(lifespan=lifespan)
```

> Including a router inside lifespan works but routes then won't appear in the OpenAPI schema generated before startup. If that matters, create the `PriceCache` at module import time and include the router there; only start/stop the source in lifespan.

### 12.2 Dependencies for route handlers

```python
# app/deps.py
from fastapi import Request

from app.market import MarketDataSource, PriceCache


def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

### 12.3 Which tickers are tracked — watchlist ∪ positions

The source must price every ticker the user **watches or holds**. Otherwise removing a held ticker from the watchlist would leave its position unpriced: portfolio value, P&L, and the heatmap break, and the user can't sell it.

```python
# app/market/startup.py
from app.db import get_held_positions, get_watchlist_tickers


def tracked_tickers(user_id: str = "default") -> list[str]:
    """Watchlist first (display order), then any held tickers not on it."""
    watch = get_watchlist_tickers(user_id)
    held = [p.ticker for p in get_held_positions(user_id)]
    return watch + [t for t in held if t not in watch]


async def start_source(source: MarketDataSource) -> None:
    tickers = tracked_tickers()
    if isinstance(source, SimulatorDataSource):
        # Continuity across restarts: start held tickers at their last trade price
        # rather than the static seed, so P&L doesn't jump on container restart.
        last = {p.ticker: p.last_price for p in get_held_positions("default") if p.last_price}
        await source.start(tickers, initial_prices=last)
    else:
        await source.start(tickers)
```

(`last_price` = price of the most recent trade for that ticker, from the `trades` table.)

### 12.4 Watchlist coordination

```python
# app/routes/watchlist.py
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
router = APIRouter(prefix="/api/watchlist")


class AddTicker(BaseModel):
    ticker: str


def normalize(ticker: str) -> str:
    t = ticker.strip().upper()
    if not TICKER_RE.match(t):
        raise HTTPException(400, f"Invalid ticker: {ticker!r}")
    return t


@router.get("")
async def list_watchlist(cache: PriceCache = Depends(get_price_cache)):
    out = []
    for t in db.get_watchlist_tickers("default"):
        u = cache.get(t)
        out.append({"ticker": t, **(u.to_dict() if u else {"price": None})})
    return out


@router.post("", status_code=201)
async def add(body: AddTicker, source=Depends(get_market_source), cache=Depends(get_price_cache)):
    t = normalize(body.ticker)
    db.add_watchlist_ticker("default", t)          # UNIQUE(user_id, ticker) → idempotent
    await source.add_ticker(t)                     # no-op if already tracked (e.g. held)
    u = cache.get(t)
    return {"ticker": t, **(u.to_dict() if u else {"price": None})}


@router.delete("/{ticker}", status_code=204)
async def remove(ticker: str, source=Depends(get_market_source)):
    t = normalize(ticker)
    db.remove_watchlist_ticker("default", t)
    if not db.has_position("default", t):          # keep pricing held tickers
        await source.remove_ticker(t)
```

The chat module's `watchlist_changes` must call the **same** service functions (not the source directly) so the held-position rule applies to AI actions too. Likewise, when a sell closes a position for a ticker that is not on the watchlist, the trade service calls `source.remove_ticker(t)`.

### 12.5 Trade execution & valuation

```python
def current_price_or_400(cache: PriceCache, ticker: str) -> float:
    price = cache.get_price(ticker)
    if price is None:
        raise HTTPException(400, f"No price available for {ticker}. Add it to the watchlist first.")
    return price


@router.post("/api/portfolio/trade")
async def trade(req: TradeRequest, cache=Depends(get_price_cache), source=Depends(get_market_source)):
    t = normalize(req.ticker)
    price = current_price_or_400(cache, t)         # fill price = latest cache value
    result = portfolio.execute(t, req.side, req.quantity, price)   # validates cash/shares
    if req.side == "buy":
        await source.add_ticker(t)                 # ensure it stays priced while held
    ...
```

Valuation (`GET /api/portfolio`, the 30 s snapshot task, chat context) reads `cache.get_all()` once per request and computes everything from that one snapshot, so values in a single response are mutually consistent. If a held ticker momentarily has no price, fall back to its `avg_cost` and flag `"stale": true` rather than dropping it from the total.

---

## 13. Error Handling & Edge Cases

| Case | Behaviour |
|---|---|
| Empty watchlist at startup | Source starts with `[]`; simulator `step()` returns `{}`; Massive skips the poll; SSE sends `data: {}`. |
| Ticker removed during Massive request | Filtered after the await (§9.4); not resurrected. |
| Ticker removed during simulator tick | Impossible — tick and cache writes contain no `await`. |
| Trade on a ticker with no cache entry | HTTP 400 with a clear message; the LLM gets the same text in its action results. |
| Unknown symbol in simulator | Priced from `seed_price_for()` with default params — any string "works" (acceptable for a simulator). |
| Unknown symbol in Massive | No snapshot returned → `price: null`; trades rejected. |
| Invalid / expired Massive key | ERROR log; backoff up to 120 s; app stays up; prices stay empty. |
| 429 rate limit | Backoff, then resumes at base interval. |
| Simulator step raises | Logged with traceback; loop continues next tick. |
| Client disconnects from SSE | `is_disconnected()` ends the generator; uvicorn also cancels it on shutdown. |
| Many SSE clients | Each generator costs one `get_all()` + `json.dumps` per changed version; trivial at single-user scale. |
| Container restart | Simulator re-seeds; held tickers restart at last trade price (§12.3). Frontend sparklines restart (by design). |

---

## 14. Configuration

| Setting | Default | Where |
|---|---|---|
| `MASSIVE_API_KEY` | empty → simulator | env / `.env` |
| `MASSIVE_POLL_INTERVAL` | `15` seconds | env (🔧 new) |
| Simulator tick | `0.5` s | `SimulatorDataSource(update_interval=...)` |
| Event probability | `0.001` per ticker per tick | `SimulatorDataSource(event_probability=...)` |
| SSE cadence | `0.5` s | `_generate_events(interval=...)` |
| SSE keepalive | `15` s | `KEEPALIVE_SECONDS` |
| SSE client retry | `1000` ms | `retry:` directive |
| Massive max backoff | `120` s | `MAX_BACKOFF_SECONDS` |

---

## 15. Testing

Existing suite: `backend/tests/market/` (73 tests). Run with `cd backend && uv run --extra dev pytest -v`. Additions below cover the 🔧 changes and the gaps called out in `archive/MARKET_DATA_REVIEW.md` (SSE untested, no full-10-ticker Cholesky test).

### 15.1 Simulator

```python
import numpy as np
import pytest

from app.market.seed_prices import SEED_PRICES
from app.market.simulator import GBMSimulator


def test_cholesky_succeeds_for_full_default_set():
    sim = GBMSimulator(list(SEED_PRICES))
    assert sim._cholesky is not None and sim._cholesky.shape == (10, 10)


def test_deterministic_with_seeded_rng():
    a = GBMSimulator(["AAPL", "TSLA"], rng=np.random.default_rng(7))
    b = GBMSimulator(["AAPL", "TSLA"], rng=np.random.default_rng(7))
    assert [a.step() for _ in range(50)] == [b.step() for _ in range(50)]


def test_volatility_matches_sigma():
    """Realized per-tick log-return std ≈ sigma * sqrt(dt)."""
    sim = GBMSimulator(["TSLA"], event_probability=0.0, rng=np.random.default_rng(0))
    prices = [sim.get_price("TSLA")]
    for _ in range(20_000):
        sim.step()
        prices.append(sim.get_price("TSLA"))
    rets = np.diff(np.log(prices))
    expected = 0.50 * np.sqrt(GBMSimulator.DEFAULT_DT)
    assert rets.std() == pytest.approx(expected, rel=0.05)


def test_tech_pair_more_correlated_than_cross_sector():
    sim = GBMSimulator(["AAPL", "MSFT", "JPM"], event_probability=0.0,
                       rng=np.random.default_rng(1))
    hist = {t: [sim.get_price(t)] for t in sim.get_tickers()}
    for _ in range(5_000):
        sim.step()
        for t in hist:
            hist[t].append(sim.get_price(t))
    r = {t: np.diff(np.log(v)) for t, v in hist.items()}
    assert np.corrcoef(r["AAPL"], r["MSFT"])[0, 1] > np.corrcoef(r["AAPL"], r["JPM"])[0, 1]


def test_unknown_ticker_seed_is_stable():
    assert GBMSimulator(["PYPL"]).get_price("PYPL") == GBMSimulator(["PYPL"]).get_price("PYPL")
```

### 15.2 Cache

```python
import threading

from app.market.cache import PriceCache


def test_session_open_carried_forward_and_day_change():
    c = PriceCache()
    c.update("AAPL", 100.0)
    u = c.update("AAPL", 102.0)
    assert u.session_open == 100.0 and u.day_change_percent == 2.0


def test_remove_bumps_version():
    c = PriceCache()
    c.update("AAPL", 100.0)
    v = c.version
    c.remove("AAPL")
    assert c.version == v + 1


def test_zero_timestamp_is_respected():
    assert PriceCache().update("X", 1.0, timestamp=0.0).timestamp == 0.0


def test_concurrent_writers():
    c = PriceCache()
    def writer(t):
        for i in range(1000):
            c.update(t, 100 + i)
    threads = [threading.Thread(target=writer, args=(f"T{i}",)) for i in range(8)]
    for th in threads: th.start()
    for th in threads: th.join()
    assert len(c) == 8 and c.version == 8000
```

### 15.3 Massive (mocked — no network)

```python
from types import SimpleNamespace as NS
from unittest.mock import patch

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource


def snap(ticker, price, prev_close=100.0, ts=1_761_134_400_000_000_000):
    return NS(ticker=ticker, last_trade=NS(price=price, sip_timestamp=ts),
              prev_day=NS(close=prev_close), min=None, day=None, updated=None)


async def test_real_snapshot_model_is_parsed():
    """Use the library's own model, not a mock, so attribute names are checked for real."""
    from massive.rest.models import TickerSnapshot
    real = TickerSnapshot.from_dict({
        "ticker": "AAPL",
        "lastTrade": {"p": 190.1, "t": 1_761_134_399_000_000_000},
        "prevDay": {"c": 191.33},
    })
    cache = PriceCache()
    src = MassiveDataSource("k", cache)
    src._client = object()
    src._tickers = ["AAPL"]
    with patch.object(src, "_fetch_snapshots", return_value=[real]):
        await src._poll_once()
    u = cache.get("AAPL")
    assert u is not None and u.price == 190.1 and u.session_open == 191.33
    assert abs(u.timestamp - 1_761_134_399) < 1


async def test_poll_maps_fields():
    cache = PriceCache()
    src = MassiveDataSource("k", cache)
    src._client = object()
    src._tickers = ["AAPL"]
    with patch.object(src, "_fetch_snapshots", return_value=[snap("AAPL", 102.0)]):
        await src._poll_once()
    u = cache.get("AAPL")
    assert u.price == 102.0 and u.session_open == 100.0
    assert abs(u.timestamp - 1_761_134_400) < 1           # ns → s


async def test_removed_ticker_not_resurrected():
    cache = PriceCache()
    src = MassiveDataSource("k", cache)
    src._client = object()
    src._tickers = ["AAPL", "GOOGL"]

    def fetch(tickers):
        src._tickers.remove("GOOGL")                       # removal races the request
        return [snap("AAPL", 1.0), snap("GOOGL", 2.0)]

    with patch.object(src, "_fetch_snapshots", side_effect=fetch):
        await src._poll_once()
    assert "GOOGL" not in cache


async def test_falls_back_when_last_trade_missing():
    cache = PriceCache()
    src = MassiveDataSource("k", cache)
    src._client = object()
    src._tickers = ["AAPL"]
    s = snap("AAPL", 0)
    s.last_trade, s.day = None, NS(close=150.0)
    with patch.object(src, "_fetch_snapshots", return_value=[s]):
        await src._poll_once()
    assert cache.get_price("AAPL") == 150.0


async def test_failure_triggers_backoff():
    src = MassiveDataSource("k", PriceCache(), poll_interval=10)
    src._client = object()
    src._tickers = ["AAPL"]
    with patch.object(src, "_fetch_snapshots", side_effect=RuntimeError("429")):
        await src._poll_once()
        await src._poll_once()
    assert src._next_delay() == 40
```

### 15.4 SSE (generator-level — avoids an infinite HTTP response in tests)

```python
import json

from app.market.cache import PriceCache
from app.market.stream import _generate_events


class FakeRequest:
    client = None
    def __init__(self, frames_before_disconnect: int):
        self._n = frames_before_disconnect
    async def is_disconnected(self):
        self._n -= 1
        return self._n < 0


async def test_stream_emits_retry_then_snapshot():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = [e async for e in _generate_events(cache, FakeRequest(1), interval=0)]
    assert events[0] == "retry: 1000\n\n"
    body = json.loads(events[1].removeprefix("data: ").strip())
    assert body["AAPL"]["price"] == 190.0 and body["AAPL"]["direction"] == "flat"


async def test_stream_skips_unchanged_versions():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    events = [e async for e in _generate_events(cache, FakeRequest(5), interval=0)]
    assert sum(e.startswith("data:") for e in events) == 1


def test_router_factory_is_reentrant():
    from app.market.stream import create_stream_router
    r1, r2 = create_stream_router(PriceCache()), create_stream_router(PriceCache())
    assert len(r1.routes) == len(r2.routes) == 1
```

### 15.5 Interface conformance (both sources)

```python
import pytest

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource


@pytest.fixture(params=["sim", "massive"])
async def source(request):
    cache = PriceCache()
    if request.param == "sim":
        src = SimulatorDataSource(cache, update_interval=0.01)
    else:
        src = MassiveDataSource("k", cache, poll_interval=0.01)
        src._fetch_snapshots = lambda tickers: []          # no network
    await src.start(["AAPL"])
    yield src, cache
    await src.stop()


async def test_add_remove_idempotent(source):
    src, cache = source
    await src.add_ticker("tsla ")
    await src.add_ticker("TSLA")
    assert src.get_tickers().count("TSLA") == 1
    await src.remove_ticker("TSLA")
    await src.remove_ticker("TSLA")
    assert "TSLA" not in src.get_tickers() and "TSLA" not in cache


async def test_stop_is_idempotent(source):
    src, _ = source
    await src.stop()
    await src.stop()
```

(For the Massive branch, patch `app.market.massive_client.RESTClient` so `start()` doesn't build a real client.)

### 15.6 E2E hooks (`test/`)

E2E runs with the simulator (no `MASSIVE_API_KEY`). Assert: the header status dot turns green within 2 s; each of the 10 default tickers shows a price within 2 s; a price cell receives a flash class within 3 s; adding `PYPL` shows a price on the next frame; removing it drops the row.

---

## 16. Implementation Checklist

Ordered; each item is small and independently testable. Items 1–9 are changes to existing market code; 10–13 are integration work for the backend agent. **Do item 6 first.** Without it, Massive mode produces no prices at all.

| # | Change | File(s) | Test |
|---|---|---|---|
| 1 | Add `session_open`, `day_change`, `day_change_percent` to `PriceUpdate` / `to_dict` | `models.py` | §15.2 |
| 2 | `PriceCache.update(session_open=...)`, `timestamp is None` check, `version` under lock, `remove` bumps version | `cache.py` | §15.2 |
| 3 | `seed_price_for()` — deterministic unknown-ticker seeds | `seed_prices.py`, `simulator.py` | §15.1 |
| 4 | Injectable `rng` and `initial_prices` in `GBMSimulator`; `initial_prices` on `SimulatorDataSource.start` | `simulator.py` | §15.1 |
| 5 | Ticker normalization in `SimulatorDataSource`; don't reset cache entry on re-add | `simulator.py` | §15.5 |
| 6 | Massive: **`sip_timestamp` fix (blocking)**, list copy to thread, post-await filter, price fallback chain, `prev_day.close` as `session_open`, timestamp normalization, backoff | `massive_client.py` | §15.3 |
| 7 | `MASSIVE_POLL_INTERVAL` env var | `factory.py` | factory test |
| 8 | Router created per call; keepalive comments; send `data: {}` when empty | `stream.py` | §15.4 |
| 9 | Add `httpx` to dev deps; shared conformance test | `pyproject.toml`, `tests/market/` | §15.5 |
| 10 | Lifespan wiring + `app.state` + deps | `main.py`, `deps.py` | route tests |
| 11 | Track watchlist ∪ positions; restart continuity | `market/startup.py` | integration |
| 12 | Watchlist routes + chat watchlist actions share one service honoring the held-position rule | `routes/watchlist.py`, chat | route tests |
| 13 | Trade fill from `PriceCache`; 400 on missing price; `add_ticker` on buy, conditional `remove_ticker` on full sell | `routes/portfolio.py` | route tests |

After each step: `uv run --extra dev pytest -q && uv run --extra dev ruff check app/ tests/`.
