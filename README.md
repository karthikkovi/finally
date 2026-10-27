# FinAlly — AI Trading Workstation

A visually stunning AI-powered trading workstation that streams live market data, simulates portfolio trading, and integrates an LLM chat assistant that can analyze positions and execute trades via natural language.

Built entirely by coding agents as a capstone project for an agentic AI coding course.

## Features

- **Live price streaming** via SSE with green/red flash animations
- **Simulated portfolio** — $10k virtual cash, market orders, instant fills
- **Portfolio visualizations** — heatmap (treemap), P&L chart, positions table
- **AI chat assistant** — analyzes holdings, suggests and auto-executes trades
- **Watchlist management** — track tickers manually or via AI
- **Dark terminal aesthetic** — Bloomberg-inspired, data-dense layout

## Architecture

Single Docker container serving everything on port 8000:

- **Frontend**: Next.js (static export) with TypeScript and Tailwind CSS
- **Backend**: FastAPI (Python/uv) with SSE streaming
- **Database**: SQLite with lazy initialization (persisted in the `finally-data` Docker volume)
- **AI**: LiteLLM → OpenRouter (Cerebras inference) with structured outputs
- **Market data**: Built-in GBM simulator (default) or Massive API (optional)

## Quick Start

Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (running).

```bash
cp .env.example .env          # then add your OPENROUTER_API_KEY
./scripts/start_mac.sh        # macOS / Linux / WSL
```

On Windows (PowerShell):

```powershell
Copy-Item .env.example .env
.\scripts\start_windows.ps1
```

Open http://localhost:8000. The start script builds the image on first run, starts a container named `finally`, waits for the health check, and opens the browser.

| Command | What it does |
|---|---|
| `./scripts/start_mac.sh` | Build image if missing, (re)start the container |
| `./scripts/start_mac.sh --build` | Force an image rebuild (after code changes) |
| `./scripts/start_mac.sh --no-open` | Don't open the browser |
| `./scripts/stop_mac.sh` | Stop and remove the container (data is kept) |

PowerShell equivalents: `start_windows.ps1 [-Build] [-NoOpen]`, `stop_windows.ps1`. Set `PORT` to use a host port other than 8000.

Your portfolio lives in the `finally-data` Docker volume and survives stop/start and rebuilds. To reset to a fresh $10k account:

```bash
./scripts/stop_mac.sh && docker volume rm finally-data
```

### Docker Compose / plain Docker

```bash
docker compose up --build -d     # or:
docker build -t finally .
docker run -d --name finally -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

> **WSL users:** enable Docker Desktop → Settings → Resources → WSL Integration for your distro so `docker` is on PATH, and add your user to the `docker` group (`sudo usermod -aG docker $USER`, then restart the shell) so it runs without `sudo`.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | For AI chat | OpenRouter API key for AI chat |
| `MASSIVE_API_KEY` | No | Massive (Polygon.io) key for real market data; omit to use the simulator |
| `LLM_MOCK` | No | Set `true` for deterministic mock LLM responses (testing, no API key needed) |

## Development Setup

Run the backend and frontend separately for hot reload. Requires [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
# Backend — http://localhost:8000 (reads .env from the repo root; DB at db/finally.db)
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8000

# Frontend — http://localhost:3000 (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

To serve the production frontend from the backend locally, run `npm run build` in `frontend/` and copy `frontend/out/` to `backend/static/` (or point `STATIC_DIR` at it).

## Testing

```bash
# Backend unit tests (pytest)
cd backend && uv run --extra dev pytest

# Frontend unit tests (Vitest + React Testing Library)
cd frontend && npm test

# End-to-end tests (Playwright, runs the app in Docker with LLM_MOCK=true)
docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from playwright
```

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project (app/, tests/)
├── planning/    # Project documentation and agent contracts
├── test/        # Playwright E2E tests + docker-compose.test.yml
├── db/          # SQLite location for local (non-Docker) runs
├── scripts/     # Start/stop helpers
├── Dockerfile   # Multi-stage build (Node → Python)
└── docker-compose.yml
```

## License

See [LICENSE](LICENSE).
