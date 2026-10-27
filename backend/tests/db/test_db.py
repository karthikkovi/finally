import sqlite3
import threading

import pytest

from app import db


def _count(path, table):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# --- init / seed --------------------------------------------------------------


def test_init_creates_parent_dir_tables_and_seed(db_path):
    assert not db_path.parent.exists()
    db.init_db()
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "users_profile",
        "watchlist",
        "positions",
        "trades",
        "portfolio_snapshots",
        "chat_messages",
    } <= tables
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()
    assert db.get_cash_balance() == 10000.0
    assert db.get_watchlist() == db.DEFAULT_TICKERS


def test_init_is_idempotent(db_path):
    db.init_db()
    db.init_db()
    db.init_db()
    assert _count(db_path, "users_profile") == 1
    assert _count(db_path, "watchlist") == 10


def test_init_does_not_reseed_or_reset_existing_data(db_path):
    db.init_db()
    db.set_cash_balance(1234.5)
    for t in db.DEFAULT_TICKERS:
        db.remove_from_watchlist(t)
    db.init_db()
    assert db.get_cash_balance() == 1234.5
    assert db.get_watchlist() == []


def test_lazy_init_on_first_call(db_path):
    assert db.get_watchlist() == db.DEFAULT_TICKERS


def test_lazy_init_recreates_deleted_file(db_path):
    db.init_db()
    db.set_cash_balance(1.0)
    for f in db_path.parent.iterdir():
        f.unlink()
    assert db.get_cash_balance() == 10000.0


def test_default_db_path_is_repo_db_dir(monkeypatch):
    monkeypatch.delenv("DB_PATH", raising=False)
    path = db.get_db_path()
    assert path.name == "finally.db"
    assert path.parent.name == "db"
    assert (path.parent.parent / "backend").is_dir()


# --- cash ---------------------------------------------------------------------


def test_set_and_get_cash(db_path):
    db.set_cash_balance(42.25)
    assert db.get_cash_balance() == 42.25


def test_unknown_user_gets_default_profile(db_path):
    assert db.get_cash_balance(user_id="alice") == 10000.0
    db.set_cash_balance(5.0, user_id="alice")
    assert db.get_cash_balance(user_id="alice") == 5.0
    assert db.get_cash_balance() == 10000.0


# --- watchlist ----------------------------------------------------------------


def test_watchlist_add_remove(db_path):
    assert db.add_to_watchlist("pypl") is True
    assert db.get_watchlist()[-1] == "PYPL"
    assert db.add_to_watchlist("PYPL") is False
    assert db.get_watchlist().count("PYPL") == 1
    assert db.remove_from_watchlist("PYPL") is True
    assert db.remove_from_watchlist("PYPL") is False
    assert "PYPL" not in db.get_watchlist()


def test_watchlist_is_per_user(db_path):
    assert db.add_to_watchlist("AAPL", user_id="bob") is True
    assert db.get_watchlist(user_id="bob") == ["AAPL"]
    assert "AAPL" in db.get_watchlist()


def test_watchlist_ordered_by_insertion(db_path):
    for t in ["ZZZ", "AAA", "MMM"]:
        db.add_to_watchlist(t)
    assert db.get_watchlist()[-3:] == ["ZZZ", "AAA", "MMM"]


# --- positions ----------------------------------------------------------------


def test_position_crud(db_path):
    assert db.get_positions() == []
    assert db.get_position("AAPL") is None
    db.upsert_position("AAPL", 10, 190.0)
    pos = db.get_position("AAPL")
    assert pos["ticker"] == "AAPL"
    assert pos["quantity"] == 10.0
    assert pos["avg_cost"] == 190.0
    assert pos["updated_at"]

    db.upsert_position("AAPL", 15.5, 191.0)
    assert db.get_position("aapl")["quantity"] == 15.5
    assert len(db.get_positions()) == 1
    assert _count(db_path, "positions") == 1

    db.upsert_position("MSFT", 1, 400.0)
    assert [p["ticker"] for p in db.get_positions()] == ["AAPL", "MSFT"]
    assert set(db.get_positions()[0]) == {"ticker", "quantity", "avg_cost", "updated_at"}

    db.delete_position("AAPL")
    assert db.get_position("AAPL") is None
    db.delete_position("AAPL")  # no-op
    assert [p["ticker"] for p in db.get_positions()] == ["MSFT"]


def test_unique_constraint_on_positions(db_path):
    db.upsert_position("AAPL", 1, 1.0)
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES ('x', 'default', 'AAPL', 1, 1, 'now')"
            )


def test_unique_constraint_on_watchlist(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) "
                "VALUES ('x', 'default', 'AAPL', 'now')"
            )


# --- trades -------------------------------------------------------------------


def test_insert_and_get_trades(db_path):
    t1 = db.insert_trade("aapl", "buy", 2, 190.0)
    assert set(t1) == {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert t1["ticker"] == "AAPL"
    t2 = db.insert_trade("AAPL", "sell", 1, 195.0)
    trades = db.get_trades()
    assert [t["id"] for t in trades] == [t2["id"], t1["id"]]  # newest first
    assert trades[1] == t1
    assert len(db.get_trades(limit=1)) == 1
    assert db.get_trades(user_id="other") == []


def test_trade_side_check(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_trade("AAPL", "hold", 1, 1.0)


# --- snapshots ----------------------------------------------------------------


def test_snapshots_oldest_first_with_limit(db_path):
    for v in [100.0, 200.0, 300.0]:
        db.insert_snapshot(v)
    snaps = db.get_snapshots()
    assert [s["total_value"] for s in snaps] == [100.0, 200.0, 300.0]
    assert set(snaps[0]) == {"total_value", "recorded_at"}
    assert [s["total_value"] for s in db.get_snapshots(limit=2)] == [200.0, 300.0]


# --- chat ---------------------------------------------------------------------


def test_chat_round_trip(db_path):
    actions = {
        "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 5, "status": "executed"}],
        "watchlist_changes": [],
    }
    u = db.insert_chat_message("user", "buy 5 AAPL", None)
    a = db.insert_chat_message("assistant", "Done.", actions)
    assert set(a) == {"id", "role", "content", "actions", "created_at"}
    msgs = db.get_chat_messages()
    assert msgs == [u, a]
    assert msgs[0]["actions"] is None
    assert msgs[1]["actions"] == actions


def test_chat_list_actions_and_limit(db_path):
    for i in range(5):
        db.insert_chat_message("assistant", f"m{i}", [{"i": i}])
    msgs = db.get_chat_messages(limit=2)
    assert [m["content"] for m in msgs] == ["m3", "m4"]
    assert msgs[1]["actions"] == [{"i": 4}]


def test_chat_role_check(db_path):
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_chat_message("system", "x", None)


# --- transactions -------------------------------------------------------------


def test_transaction_commits(db_path):
    with db.transaction() as conn:
        db.set_cash_balance(500.0, conn=conn)
        db.upsert_position("AAPL", 2, 250.0, conn=conn)
        db.insert_trade("AAPL", "buy", 2, 250.0, conn=conn)
        db.insert_snapshot(1000.0, conn=conn)
        assert db.get_cash_balance(conn=conn) == 500.0
        assert db.get_position("AAPL", conn=conn)["quantity"] == 2
    assert db.get_cash_balance() == 500.0
    assert len(db.get_trades()) == 1
    assert len(db.get_snapshots()) == 1


def test_transaction_rolls_back_on_error(db_path):
    db.init_db()
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            db.set_cash_balance(1.0, conn=conn)
            db.upsert_position("AAPL", 2, 250.0, conn=conn)
            db.insert_trade("AAPL", "buy", 2, 250.0, conn=conn)
            db.insert_snapshot(1000.0, conn=conn)
            raise RuntimeError("boom")
    assert db.get_cash_balance() == 10000.0
    assert db.get_position("AAPL") is None
    assert db.get_trades() == []
    assert db.get_snapshots() == []


def test_get_positions_on_transaction_conn(db_path):
    with db.transaction() as conn:
        db.upsert_position("MSFT", 1, 400.0, conn=conn)
        db.upsert_position("AAPL", 2, 250.0, conn=conn)
        # Sees uncommitted writes on the same connection, without deadlocking
        assert [p["ticker"] for p in db.get_positions(conn=conn)] == ["AAPL", "MSFT"]
    assert [p["ticker"] for p in db.get_positions()] == ["AAPL", "MSFT"]


def test_concurrent_writes_from_threads(db_path):
    db.init_db()
    errors = []

    def worker(n):
        try:
            for _ in range(10):
                with db.transaction() as conn:
                    cash = db.get_cash_balance(conn=conn)
                    db.set_cash_balance(cash - 1, conn=conn)
                    db.insert_trade(f"T{n}", "buy", 1, 1.0, conn=conn)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert db.get_cash_balance() == 10000.0 - 40
    assert len(db.get_trades(limit=1000)) == 40
