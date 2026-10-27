"""SQLite connection management, lazy initialization, and transactions."""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_USER_ID = "default"
DEFAULT_CASH_BALANCE = 10000.0
DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_REPO_ROOT = Path(__file__).resolve().parents[3]

_init_lock = threading.Lock()
_initialized_paths: set[str] = set()


def get_db_path() -> Path:
    """Resolve the database path from ``DB_PATH`` (read on every call so tests can override it)."""
    env = os.environ.get("DB_PATH")
    return Path(env) if env else _REPO_ROOT / "db" / "finally.db"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def _dict_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def _connect(path: Path) -> sqlite3.Connection:
    # isolation_level=None: autocommit; transactions are opened explicitly with BEGIN.
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=10.0)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def init_db() -> None:
    """Create tables if missing and seed the default user and watchlist. Idempotent."""
    path = get_db_path()
    with _init_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = _connect(path)
        try:
            conn.executescript(_SCHEMA_PATH.read_text())
            conn.execute("BEGIN IMMEDIATE")
            try:
                created = conn.execute(
                    "INSERT OR IGNORE INTO users_profile (id, cash_balance, created_at) "
                    "VALUES (?, ?, ?)",
                    (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, now_iso()),
                ).rowcount
                # Seed the watchlist only when the default user is brand new, so a user
                # who removes every ticker doesn't get them back on restart.
                if created:
                    for ticker in DEFAULT_TICKERS:
                        conn.execute(
                            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) "
                            "VALUES (?, ?, ?, ?)",
                            (new_id(), DEFAULT_USER_ID, ticker, now_iso()),
                        )
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()
        _initialized_paths.add(str(path))


def get_connection() -> sqlite3.Connection:
    """Open a new connection, initializing the database on first use of this path."""
    path = get_db_path()
    if str(path) not in _initialized_paths or not path.exists():
        _initialized_paths.discard(str(path))
        init_db()
    return _connect(path)


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Atomic multi-step write. Commits on success, rolls back on any exception."""
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
    finally:
        conn.close()


@contextmanager
def use_connection(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Use the caller's connection (inside their transaction) or run in a fresh transaction."""
    if conn is not None:
        yield conn
    else:
        with transaction() as own:
            yield own
