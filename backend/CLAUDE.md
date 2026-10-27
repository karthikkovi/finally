# Backend — Developer Guide

FastAPI app (`app.main:app`) serving the REST API, the SSE price stream, and the static frontend export.
The API contract (request/response shapes, ownership) lives in `planning/TEAM.md`.

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
LLM_MOCK=true uv run uvicorn app.main:app --port 8000   # Run locally
```

Environment (read from `<repo>/.env` if present):

| Var | Default | Effect |
|---|---|---|
| `DB_PATH` | `<repo>/db/finally.db` | SQLite file (created + seeded lazily) |
| `STATIC_DIR` | `backend/static` | Next.js export served at `/` with `index.html` fallback, if the dir exists |
| `MASSIVE_API_KEY` | empty | Set → Massive REST poller, else GBM simulator |
| `LLM_MOCK` | `false` | `true` → deterministic mock chat responses |
| `SNAPSHOT_INTERVAL` | `30` | Seconds between background portfolio snapshots |

## Layout

- `app/main.py` — lifespan: `db.init_db()`, start market source on watchlist ∪ held positions, record a
  snapshot, run the 30 s snapshot loop. Routers: health, portfolio, watchlist, stream, chat. SPA catch-all
  is registered last and never swallows `/api/*` (unknown API paths 404 as JSON).
- `app/market/` — price cache, data sources, SSE (see below).
- `app/services/` — business logic shared by REST routes and the LLM:
  - `execute_trade(ticker, side, quantity, price_cache) -> dict` — validates, runs in one DB
    transaction (weighted avg cost on buy, position deleted when it hits 0), records a snapshot.
    Raises `TradeError` with a user-facing message.
  - `get_portfolio(price_cache)`, `record_snapshot(price_cache)`, `get_history()`
  - `add_watchlist_ticker(ticker, source)` / `remove_watchlist_ticker(ticker, source)` (async; raise
    `ValueError` for invalid tickers, return `False` for duplicate/missing). Removing a ticker that is
    still held keeps it streaming.
  - `normalize_ticker`, `tracked_tickers`, `get_watchlist_with_prices`
- `app/routes/` — thin HTTP wrappers; `deps.py` exposes `PriceCacheDep` / `MarketSourceDep` from
  `app.state`. `chat.py` is owned by the LLM engineer.
- `app/db/`, `app/llm/` — owned by other team members.

## Market Data API

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, create_market_data_source
```

- **`PriceUpdate`** — frozen dataclass: `ticker`, `price`, `previous_price`, `timestamp`, `open_price`
  (first price seen this session) plus properties `change`, `change_percent`, `change_percent_open`,
  `direction` ("up"/"down"/"flat"), and `to_dict()`.
- **`PriceCache`** — thread-safe: `update(ticker, price, timestamp=None)`, `get`, `get_price`, `get_all`,
  `remove`, and a `version` counter bumped on every mutation (SSE change detection).
- **`MarketDataSource`** — `start(tickers)` → `add_ticker()` / `remove_ticker()` → `stop()`;
  `get_tickers()`. Implemented by `SimulatorDataSource` (GBM, correlated, random 2–5% events, 500 ms)
  and `MassiveDataSource` (REST snapshot polling, 15 s).
- **`create_market_data_source(cache)`** — Massive if `MASSIVE_API_KEY` is non-empty, else simulator.
- **`create_stream_router(cache)`** — `GET /api/stream/prices`: sends `retry: 1000`, then a
  `data: {TICKER: PriceUpdate.to_dict(), ...}` event every ~500 ms when the cache changed.

Seed prices, per-ticker volatility/drift, and correlation groups are in `app/market/seed_prices.py`.

## Running Tests

```bash
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
uv run --extra dev ruff format app/ tests/
```

`tests/conftest.py` provides `temp_db`, `seeded_db`, `cache` (AAPL=100, MSFT=400) and `fake_source`
(a recording in-memory `MarketDataSource`). Tests: `tests/market/`, `tests/services/`, `tests/routes/`.

## Demo

```bash
uv run market_data_demo.py   # Live terminal dashboard with simulated prices
```
