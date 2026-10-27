#!/usr/bin/env bash
# Start FinAlly in Docker (macOS/Linux/WSL). Idempotent: safe to run repeatedly.
#
# Usage: scripts/start_mac.sh [--build] [--no-open]
#   --build    Force a rebuild of the Docker image
#   --no-open  Don't open the browser
set -euo pipefail

IMAGE="finally"
CONTAINER="finally"
VOLUME="finally-data"
PORT="${PORT:-8000}"
URL="http://localhost:${PORT}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

BUILD=0
OPEN=1
for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --no-open) OPEN=0 ;;
        -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

if ! docker info >/dev/null 2>&1; then
    echo "Error: the Docker daemon is not running. Start Docker Desktop and retry." >&2
    exit 1
fi

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Created .env from .env.example — add your OPENROUTER_API_KEY to enable AI chat."
    else
        touch .env
    fi
fi

if [ "$BUILD" -eq 1 ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building Docker image '$IMAGE'..."
    docker build -t "$IMAGE" .
fi

# Replace any existing container (running or stopped); the volume is kept
if docker container inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "Removing existing container '$CONTAINER'..."
    docker rm -f "$CONTAINER" >/dev/null
fi

# Fail fast if another process already serves the port; otherwise the health check below could pass against it
if curl -s -o /dev/null --max-time 2 "${URL}"; then
    echo "Error: something is already listening on port ${PORT}. Stop it or run with PORT=<other> $0" >&2
    exit 1
fi

echo "Starting container '$CONTAINER'..."
docker run -d \
    --name "$CONTAINER" \
    -p "${PORT}:8000" \
    -v "${VOLUME}:/app/db" \
    --env-file .env \
    --restart unless-stopped \
    "$IMAGE" >/dev/null

printf "Waiting for FinAlly to become healthy"
for _ in $(seq 1 60); do
    if curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
        echo
        echo "FinAlly is running at ${URL}"
        break
    fi
    printf "."
    sleep 1
done
if ! curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
    echo
    echo "Warning: FinAlly did not respond on ${URL} yet. Check logs with: docker logs $CONTAINER" >&2
    exit 1
fi

if [ "$OPEN" -eq 1 ]; then
    if command -v open >/dev/null 2>&1; then
        open "$URL" >/dev/null 2>&1 || true
    elif command -v wslview >/dev/null 2>&1; then
        wslview "$URL" >/dev/null 2>&1 || true
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open "$URL" >/dev/null 2>&1 || true
    fi
fi
