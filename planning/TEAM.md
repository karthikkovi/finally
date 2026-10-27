# FinAlly — Agent Team Contract

This is the shared contract for the agent team building FinAlly. `PLAN.md` is the spec; this file pins down
ownership, module interfaces, and API shapes so team members can work in parallel. If you need to change
anything here, message the owner(s) affected and the `team-lead`, then update this file.

## Team & Ownership

| Name | Role | Owns (only this member edits these) |
|---|---|---|
| `database` | Database Engineer | `backend/app/db/`, `backend/tests/db/` |
| `backend` | Backend API Engineer | `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/main.py`, `backend/app/market/`, `backend/app/services/`, `backend/app/routes/` (except `chat.py`), `backend/tests/` (except `db/`, `llm/`), `backend/CLAUDE.md` |
| `llm` | LLM Engineer | `backend/app/llm/`, `backend/app/routes/chat.py`, `backend/tests/llm/` |
| `frontend` | Frontend Engineer | `frontend/` |
| `devops` | DevOps Engineer | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/`, `.env.example`, `.gitignore`, `README.md` |
| `tester` | Integration Tester | `test/` (Playwright E2E + `test/docker-compose.test.yml`) |

Rules:
- Don't edit files you don't own. Ask the owner via message instead (include the exact change you need).
- Python dependencies: only `backend` edits `pyproject.toml`. Message `backend` with packages you need.
- Do **not** `git commit` / `git push` — the team lead commits.
- Everyone writes unit tests for their own code. Backend: pytest. Frontend: Vitest + React Testing Library.
- Toolchain: `uv` is at `~/.local/bin/uv`. Node 24 / npm available. Docker is Docker Desktop (via WSL).
- The market-data module is being **rebuilt from scratch** by `backend` (the old code was deleted). The design in
  `planning/MARKET_DATA_SUMMARY.md` and `planning/archive/*` is the reference.

## Backend Layout (`backend/`, Python package `app`)

```
app/
  main.py            # FastAPI app, lifespan (init DB, start market source, snapshot task), static mount   [backend]
  market/            # PriceCache, PriceUpdate, MarketDataSource, simulator, Massive client, SSE router    [backend]
  services/          # portfolio.py (trade execution, valuation, snapshots), watchlist.py                    [backend]
  routes/            # portfolio.py, watchlist.py, health.py                                                [backend]
  routes/chat.py     # POST /api/chat, GET /api/chat/history                                                [llm]
  llm/               # prompt building, LiteLLM call, structured output, mock mode, action execution        [llm]
  db/                # connection, schema.sql, seed, repository functions                                   [database]
```

(PLAN.md says `backend/db/`; we use `backend/app/db/` so it's importable as `app.db`.)

### Environment / paths
- `DB_PATH` env var; default `<repo root>/db/finally.db`. In Docker: `/app/db/finally.db`.
- `STATIC_DIR` env var; default `backend/static`. FastAPI serves it at `/` (with `index.html` fallback) when it exists.
- `.env` is loaded from the repo root (python-dotenv) if present; in Docker it comes from `--env-file`.
- `LLM_MOCK=true` → deterministic mock LLM. `MASSIVE_API_KEY` set → Massive, else simulator.

### `app.db` interface (owner: `database`)
Synchronous `sqlite3`, one connection per call (or a module-level helper), WAL mode, `check_same_thread=False`.
All functions take `user_id: str = "default"`. Timestamps are ISO-8601 UTC strings. IDs are UUID4 strings.

```python
init_db() -> None                       # idempotent: create tables if missing, seed default user + 10 tickers
transaction() -> ContextManager[sqlite3.Connection]   # atomic multi-step writes; repo fns accept conn=None
get_cash_balance(user_id="default", conn=None) -> float
set_cash_balance(amount: float, user_id="default", conn=None) -> None
get_watchlist(user_id="default") -> list[str]                  # ordered by added_at
add_to_watchlist(ticker, user_id="default") -> bool            # False if already present
remove_from_watchlist(ticker, user_id="default") -> bool       # False if not present
get_positions(user_id="default", conn=None) -> list[dict]      # {ticker, quantity, avg_cost, updated_at}
get_position(ticker, user_id="default", conn=None) -> dict | None
upsert_position(ticker, quantity, avg_cost, user_id="default", conn=None) -> None
delete_position(ticker, user_id="default", conn=None) -> None
insert_trade(ticker, side, quantity, price, user_id="default", conn=None) -> dict   # returns the row
get_trades(user_id="default", limit=100) -> list[dict]
insert_snapshot(total_value, user_id="default", conn=None) -> None
get_snapshots(user_id="default", limit=1000) -> list[dict]     # {total_value, recorded_at}, oldest first
insert_chat_message(role, content, actions: list|dict|None, user_id="default") -> dict
get_chat_messages(user_id="default", limit=50) -> list[dict]   # oldest first; actions decoded from JSON
```

### `app.market` interface (owner: `backend`)
As in `planning/MARKET_DATA_SUMMARY.md`: `PriceUpdate`, `PriceCache`, `MarketDataSource`,
`create_market_data_source(cache)`, `create_stream_router(cache)`. Additionally `PriceUpdate` carries
`open_price` (first price seen this session for the ticker) and `change_percent_open` (% vs `open_price`) —
used as the "daily change %" in the watchlist.

### `app.services` interface (owner: `backend`) — used by `llm`
```python
class TradeError(Exception): ...        # message is user-facing, e.g. "Insufficient cash: need $1,900.00, have $500.00"
execute_trade(ticker: str, side: Literal["buy","sell"], quantity: float, price_cache) -> dict
    # validates (qty > 0, ticker has a price, enough cash / shares), runs in one DB transaction,
    # updates cash + position (weighted avg cost on buy; delete position when qty hits 0),
    # inserts trade, records a snapshot. Returns the trade dict. Raises TradeError.
get_portfolio(price_cache) -> dict      # same shape as GET /api/portfolio
add_watchlist_ticker(ticker, market_source) -> bool      # normalizes upper-case, validates ^[A-Z.]{1,10}$, starts streaming it
remove_watchlist_ticker(ticker, market_source) -> bool
```
Both REST routes and the LLM call these — no duplicated trade logic.

## REST API (all JSON; errors are `{"detail": "<message>"}`)

| Method & path | Request | Success response |
|---|---|---|
| `GET /api/health` | — | `{"status": "ok"}` |
| `GET /api/portfolio` | — | `{"cash_balance", "total_value", "positions_value", "unrealized_pnl", "positions": [{"ticker","quantity","avg_cost","current_price","market_value","unrealized_pnl","unrealized_pnl_percent"}]}` |
| `POST /api/portfolio/trade` | `{"ticker","quantity","side"}` | 200 `{"trade": {"id","ticker","side","quantity","price","executed_at"}, "portfolio": {...as above}}`; 400 on validation failure |
| `GET /api/portfolio/history` | — | `{"snapshots": [{"total_value","recorded_at"}]}` |
| `GET /api/watchlist` | — | `{"tickers": [{"ticker","price","previous_price","change","change_percent","direction","open_price","change_percent_open"}]}` (price fields `null` until first tick) |
| `POST /api/watchlist` | `{"ticker"}` | 201 `{"ticker"}`; 400 invalid; 409 already present |
| `DELETE /api/watchlist/{ticker}` | — | 204; 404 if not present |
| `POST /api/chat` | `{"message"}` | 200 `{"message", "trades": [{"ticker","side","quantity","status":"executed"\|"failed","price"?,"error"?}], "watchlist_changes": [{"ticker","action":"add"\|"remove","status":"applied"\|"failed","error"?}]}` |
| `GET /api/chat/history` | — | `{"messages": [{"id","role","content","actions","created_at"}]}` |

Current price for a position with no cached price falls back to `avg_cost`.
Positions are valued from the `PriceCache`. A background task records a snapshot every 30 s.
Tickers held in positions but not on the watchlist must still be priced (the market source tracks watchlist ∪ positions).

### SSE: `GET /api/stream/prices`
`text/event-stream`, one event roughly every 500 ms whenever the cache version changed:
```
data: {"AAPL": {"ticker":"AAPL","price":190.12,"previous_price":190.05,"timestamp":1730000000.123,
                "change":0.07,"change_percent":0.0368,"direction":"up","open_price":190.0,"change_percent_open":0.063}, ...}
```
The payload is a map of **all** currently tracked tickers. Send `retry: 1000` on connect.

## LLM mock mode (owner: `llm`) — deterministic, relied on by E2E tests
With `LLM_MOCK=true`, `/api/chat` does not call the network. The mock parses the user message (case-insensitive):
- `buy <qty> <TICKER>` → one buy trade
- `sell <qty> <TICKER>` → one sell trade
- `add <TICKER>` / `watch <TICKER>` → watchlist add
- `remove <TICKER>` / `unwatch <TICKER>` → watchlist remove
- anything else → message `"Mock response: I can help you analyze your portfolio."` with no actions
The mock's `message` text for actions is e.g. `"Mock: buying 5 AAPL."`. Actions then go through the real execution path.

## Frontend contract (owner: `frontend`) — relied on by E2E tests
Static export (`output: 'export'`) to `frontend/out/`. Same-origin calls to `/api/*`; in `next dev`, proxy `/api` to `http://localhost:8000`.
Required `data-testid`s:

| testid | element |
|---|---|
| `connection-status` | header dot; attribute `data-status="connected" \| "reconnecting" \| "disconnected"` |
| `total-value`, `cash-balance` | header values (text like `$10,000.00`) |
| `watchlist-row-{TICKER}` | watchlist row (clicking selects ticker for main chart) |
| `watchlist-price-{TICKER}` | price cell in that row (flash class applied on change) |
| `watchlist-add-input`, `watchlist-add-button`, `watchlist-remove-{TICKER}` | watchlist management |
| `main-chart` | main chart container; attribute `data-ticker="{TICKER}"` |
| `trade-ticker`, `trade-quantity`, `trade-buy`, `trade-sell`, `trade-error` | trade bar |
| `positions-table`, `position-row-{TICKER}` | positions table |
| `heatmap`, `heatmap-cell-{TICKER}` | treemap; cells carry `data-pnl="positive" \| "negative" \| "flat"` |
| `pnl-chart` | portfolio value chart; attribute `data-points="{n}"` |
| `chat-panel`, `chat-input`, `chat-send`, `chat-loading`, `chat-message` (with `data-role`), `chat-action` | chat |

## DevOps contract (owner: `devops`)
- Multi-stage `Dockerfile`: Node 20 slim builds `frontend/out` → Python 3.12 slim with uv, `uv sync --frozen --no-dev`,
  frontend copied to `/app/backend/static`, `ENV DB_PATH=/app/db/finally.db STATIC_DIR=/app/backend/static`,
  `EXPOSE 8000`, CMD `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` from `/app/backend`.
- Image/container name `finally`, volume `finally-data:/app/db`, `--env-file .env`.
- `docker-compose.yml` at root (convenience). `test/docker-compose.test.yml` is owned by `tester` but devops helps.
