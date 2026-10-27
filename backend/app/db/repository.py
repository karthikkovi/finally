"""Repository functions over the FinAlly SQLite schema.

Write functions accept an optional ``conn``; pass the connection from ``transaction()``
to group several writes atomically. Without it, each call runs in its own transaction.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .connection import (
    DEFAULT_CASH_BALANCE,
    DEFAULT_USER_ID,
    get_connection,
    new_id,
    now_iso,
    use_connection,
)


def _read(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


# --- Cash -------------------------------------------------------------------


def get_cash_balance(
    user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> float:
    """Cash for ``user_id``. Unknown users get a fresh profile with the default balance."""
    with use_connection(conn) as c:
        row = c.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            c.execute(
                "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
                (user_id, DEFAULT_CASH_BALANCE, now_iso()),
            )
            return DEFAULT_CASH_BALANCE
        return float(row["cash_balance"])


def set_cash_balance(
    amount: float, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> None:
    with use_connection(conn) as c:
        c.execute(
            """INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)
               ON CONFLICT (id) DO UPDATE SET cash_balance = excluded.cash_balance""",
            (user_id, float(amount), now_iso()),
        )


# --- Watchlist --------------------------------------------------------------


def get_watchlist(user_id: str = DEFAULT_USER_ID) -> list[str]:
    rows = _read(
        "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at, rowid", (user_id,)
    )
    return [r["ticker"] for r in rows]


def add_to_watchlist(ticker: str, user_id: str = DEFAULT_USER_ID) -> bool:
    """Returns False if the ticker is already on the watchlist."""
    with use_connection(None) as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (new_id(), user_id, ticker.upper(), now_iso()),
        )
        return cur.rowcount > 0


def remove_from_watchlist(ticker: str, user_id: str = DEFAULT_USER_ID) -> bool:
    """Returns False if the ticker was not on the watchlist."""
    with use_connection(None) as c:
        cur = c.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?", (user_id, ticker.upper())
        )
        return cur.rowcount > 0


# --- Positions --------------------------------------------------------------


def get_positions(
    user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> list[dict]:
    with use_connection(conn) as c:
        return c.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? ORDER BY ticker",
            (user_id,),
        ).fetchall()


def get_position(
    ticker: str, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> dict | None:
    with use_connection(conn) as c:
        return c.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? AND ticker = ?",
            (user_id, ticker.upper()),
        ).fetchone()


def upsert_position(
    ticker: str,
    quantity: float,
    avg_cost: float,
    user_id: str = DEFAULT_USER_ID,
    conn: sqlite3.Connection | None = None,
) -> None:
    with use_connection(conn) as c:
        c.execute(
            """INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT (user_id, ticker) DO UPDATE SET
                   quantity = excluded.quantity,
                   avg_cost = excluded.avg_cost,
                   updated_at = excluded.updated_at""",
            (new_id(), user_id, ticker.upper(), float(quantity), float(avg_cost), now_iso()),
        )


def delete_position(
    ticker: str, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> None:
    with use_connection(conn) as c:
        c.execute(
            "DELETE FROM positions WHERE user_id = ? AND ticker = ?", (user_id, ticker.upper())
        )


# --- Trades -----------------------------------------------------------------


def insert_trade(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = DEFAULT_USER_ID,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Append a trade and return it as ``{id, ticker, side, quantity, price, executed_at}``."""
    trade = {
        "id": new_id(),
        "ticker": ticker.upper(),
        "side": side,
        "quantity": float(quantity),
        "price": float(price),
        "executed_at": now_iso(),
    }
    with use_connection(conn) as c:
        c.execute(
            """INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                trade["id"],
                user_id,
                trade["ticker"],
                side,
                trade["quantity"],
                trade["price"],
                trade["executed_at"],
            ),
        )
    return trade


def get_trades(user_id: str = DEFAULT_USER_ID, limit: int = 100) -> list[dict]:
    """Most recent trades first."""
    return _read(
        """SELECT id, ticker, side, quantity, price, executed_at FROM trades
           WHERE user_id = ? ORDER BY executed_at DESC, rowid DESC LIMIT ?""",
        (user_id, limit),
    )


# --- Portfolio snapshots ----------------------------------------------------


def insert_snapshot(
    total_value: float, user_id: str = DEFAULT_USER_ID, conn: sqlite3.Connection | None = None
) -> None:
    with use_connection(conn) as c:
        c.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (new_id(), user_id, float(total_value), now_iso()),
        )


def get_snapshots(user_id: str = DEFAULT_USER_ID, limit: int = 1000) -> list[dict]:
    """The latest ``limit`` snapshots, returned oldest first."""
    rows = _read(
        """SELECT total_value, recorded_at FROM portfolio_snapshots
           WHERE user_id = ? ORDER BY recorded_at DESC, rowid DESC LIMIT ?""",
        (user_id, limit),
    )
    rows.reverse()
    return rows


# --- Chat -------------------------------------------------------------------


def _decode_chat_row(row: dict) -> dict:
    row["actions"] = json.loads(row["actions"]) if row["actions"] is not None else None
    return row


def insert_chat_message(
    role: str, content: str, actions: list | dict | None, user_id: str = DEFAULT_USER_ID
) -> dict:
    """Store a chat message and return ``{id, role, content, actions, created_at}``."""
    message: dict[str, Any] = {
        "id": new_id(),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": now_iso(),
    }
    encoded = json.dumps(actions) if actions is not None else None
    with use_connection(None) as c:
        c.execute(
            """INSERT INTO chat_messages (id, user_id, role, content, actions, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message["id"], user_id, role, content, encoded, message["created_at"]),
        )
    return message


def get_chat_messages(user_id: str = DEFAULT_USER_ID, limit: int = 50) -> list[dict]:
    """The latest ``limit`` messages, returned oldest first, with ``actions`` decoded."""
    rows = _read(
        """SELECT id, role, content, actions, created_at FROM chat_messages
           WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?""",
        (user_id, limit),
    )
    rows.reverse()
    return [_decode_chat_row(r) for r in rows]
