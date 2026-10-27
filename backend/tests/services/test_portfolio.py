"""Trade execution, valuation, and snapshots."""

from contextlib import contextmanager

import pytest

from app import db
from app.services import TradeError, execute_trade, get_history, get_portfolio, record_snapshot
from app.services import portfolio as portfolio_mod

pytestmark = pytest.mark.usefixtures("seeded_db")


def test_buy_debits_cash_creates_position_and_logs_trade(cache):
    trade = execute_trade("aapl", "buy", 10, cache)
    assert set(trade) >= {"id", "ticker", "side", "quantity", "price", "executed_at"}
    assert (trade["ticker"], trade["side"], trade["quantity"], trade["price"]) == (
        "AAPL",
        "buy",
        10,
        100.0,
    )
    assert db.get_cash_balance() == pytest.approx(9000.0)
    pos = db.get_position("AAPL")
    assert pos["quantity"] == 10 and pos["avg_cost"] == 100.0
    assert len(db.get_trades()) == 1


def test_weighted_average_cost(cache):
    execute_trade("AAPL", "buy", 10, cache)
    cache.update("AAPL", 130.0)
    execute_trade("AAPL", "buy", 5, cache)
    pos = db.get_position("AAPL")
    assert pos["quantity"] == 15
    assert pos["avg_cost"] == pytest.approx((1000 + 650) / 15)


def test_fractional_shares(cache):
    execute_trade("AAPL", "buy", 0.5, cache)
    assert db.get_position("AAPL")["quantity"] == 0.5
    assert db.get_cash_balance() == pytest.approx(9950.0)


def test_partial_sell_keeps_avg_cost(cache):
    execute_trade("AAPL", "buy", 10, cache)
    cache.update("AAPL", 120.0)
    trade = execute_trade("AAPL", "sell", 4, cache)
    assert trade["side"] == "sell" and trade["price"] == 120.0
    pos = db.get_position("AAPL")
    assert pos["quantity"] == 6 and pos["avg_cost"] == 100.0
    assert db.get_cash_balance() == pytest.approx(9000 + 480)


def test_sell_all_deletes_position(cache):
    execute_trade("AAPL", "buy", 0.3, cache)
    execute_trade("AAPL", "sell", 0.1, cache)
    execute_trade("AAPL", "sell", 0.2, cache)  # float dust must not leave a position behind
    assert db.get_position("AAPL") is None
    assert db.get_cash_balance() == pytest.approx(10000.0)


def test_sell_at_loss(cache):
    execute_trade("AAPL", "buy", 10, cache)
    cache.update("AAPL", 80.0)
    execute_trade("AAPL", "sell", 10, cache)
    assert db.get_cash_balance() == pytest.approx(9800.0)


def test_insufficient_cash(cache):
    with pytest.raises(TradeError, match=r"Insufficient cash: need \$10,100.00, have \$10,000.00"):
        execute_trade("AAPL", "buy", 101, cache)
    assert db.get_cash_balance() == 10000.0
    assert db.get_trades() == []


def test_buy_exactly_all_cash(cache):
    execute_trade("AAPL", "buy", 100, cache)
    assert db.get_cash_balance() == pytest.approx(0.0)


def test_insufficient_shares(cache):
    execute_trade("AAPL", "buy", 2, cache)
    with pytest.raises(TradeError, match="Insufficient shares: trying to sell 3 AAPL, have 2"):
        execute_trade("AAPL", "sell", 3, cache)
    assert db.get_position("AAPL")["quantity"] == 2


def test_sell_without_position(cache):
    with pytest.raises(TradeError, match="Insufficient shares"):
        execute_trade("AAPL", "sell", 1, cache)


@pytest.mark.parametrize("qty", [0, -1, float("nan"), float("inf"), "abc", None])
def test_bad_quantity(cache, qty):
    with pytest.raises(TradeError):
        execute_trade("AAPL", "buy", qty, cache)


@pytest.mark.parametrize("side", ["hold", "", None])
def test_bad_side(cache, side):
    with pytest.raises(TradeError, match="side"):
        execute_trade("AAPL", side, 1, cache)


def test_missing_ticker(cache):
    with pytest.raises(TradeError, match="Ticker is required"):
        execute_trade("  ", "buy", 1, cache)


def test_no_price(cache):
    with pytest.raises(TradeError, match="No price available for ZZZZ"):
        execute_trade("ZZZZ", "buy", 1, cache)


def test_trade_records_snapshot(cache):
    before = len(get_history())
    execute_trade("AAPL", "buy", 1, cache)
    snaps = get_history()
    assert len(snaps) == before + 1
    assert snaps[-1]["total_value"] == pytest.approx(10000.0)


def test_failed_trade_records_no_snapshot(cache):
    with pytest.raises(TradeError):
        execute_trade("AAPL", "buy", 1000, cache)
    assert get_history() == []


def test_portfolio_empty(cache):
    assert get_portfolio(cache) == {
        "cash_balance": 10000.0,
        "total_value": 10000.0,
        "positions_value": 0.0,
        "unrealized_pnl": 0.0,
        "positions": [],
    }


def test_portfolio_valuation(cache):
    execute_trade("AAPL", "buy", 10, cache)
    execute_trade("MSFT", "buy", 2, cache)
    cache.update("AAPL", 110.0)
    cache.update("MSFT", 380.0)
    p = get_portfolio(cache)
    assert p["cash_balance"] == pytest.approx(10000 - 1000 - 800)
    assert p["positions_value"] == pytest.approx(1100 + 760)
    assert p["total_value"] == pytest.approx(p["cash_balance"] + 1860)
    assert p["unrealized_pnl"] == pytest.approx(100 - 40)
    by = {pos["ticker"]: pos for pos in p["positions"]}
    assert by["AAPL"] == {
        "ticker": "AAPL",
        "quantity": 10,
        "avg_cost": 100.0,
        "current_price": 110.0,
        "market_value": 1100.0,
        "unrealized_pnl": 100.0,
        "unrealized_pnl_percent": 10.0,
    }
    assert by["MSFT"]["unrealized_pnl_percent"] == -5.0


def test_portfolio_falls_back_to_avg_cost(cache):
    execute_trade("AAPL", "buy", 10, cache)
    cache.remove("AAPL")
    pos = get_portfolio(cache)["positions"][0]
    assert pos["current_price"] == 100.0
    assert pos["unrealized_pnl"] == 0.0


def test_record_snapshot_returns_total(cache):
    assert record_snapshot(cache) == 10000.0
    assert get_history()[-1]["total_value"] == 10000.0
    assert set(get_history()[-1]) >= {"total_value", "recorded_at"}


def test_portfolio_reads_cash_and_positions_on_one_connection(cache, monkeypatch):
    seen = {}
    real_cash, real_positions = db.get_cash_balance, db.get_positions

    def spy_cash(*args, conn=None, **kwargs):
        seen["cash"] = conn
        return real_cash(*args, conn=conn, **kwargs)

    def spy_positions(*args, conn=None, **kwargs):
        seen["positions"] = conn
        return real_positions(*args, conn=conn, **kwargs)

    monkeypatch.setattr(db, "get_cash_balance", spy_cash)
    monkeypatch.setattr(db, "get_positions", spy_positions)
    get_portfolio(cache)
    assert seen["cash"] is not None
    assert seen["cash"] is seen["positions"]


def test_snapshot_taken_after_trade_transaction_commits(cache, monkeypatch):
    """get_portfolio must never run inside execute_trade's write transaction (deadlock)."""
    depth = 0
    real_transaction = db.transaction
    real_get_portfolio = portfolio_mod.get_portfolio

    @contextmanager
    def tracking_transaction(*args, **kwargs):
        nonlocal depth
        depth += 1
        try:
            with real_transaction(*args, **kwargs) as conn:
                yield conn
        finally:
            depth -= 1

    def guarded_get_portfolio(price_cache):
        assert depth == 0, "get_portfolio called inside an open transaction"
        return real_get_portfolio(price_cache)

    monkeypatch.setattr(db, "transaction", tracking_transaction)
    monkeypatch.setattr(portfolio_mod, "get_portfolio", guarded_get_portfolio)
    execute_trade("AAPL", "buy", 1, cache)
    execute_trade("AAPL", "sell", 1, cache)
    assert len(get_history()) == 2
