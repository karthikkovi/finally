"""Trade execution, portfolio valuation, and snapshots — shared by REST routes and the LLM."""

from __future__ import annotations

import logging
from typing import Literal

from app import db
from app.market import PriceCache

logger = logging.getLogger(__name__)

# Quantities below this are treated as zero (float dust after partial sells)
QTY_EPSILON = 1e-9


class TradeError(Exception):
    """A trade failed validation. The message is user-facing."""


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _qty(value: float) -> str:
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def execute_trade(
    ticker: str,
    side: Literal["buy", "sell"],
    quantity: float,
    price_cache: PriceCache,
) -> dict:
    """Execute a market order at the cached price. Returns the trade dict; raises TradeError."""
    ticker = (ticker or "").strip().upper()
    side = (side or "").strip().lower()  # type: ignore[assignment]
    if not ticker:
        raise TradeError("Ticker is required")
    if side not in ("buy", "sell"):
        raise TradeError(f"Invalid side '{side}': must be 'buy' or 'sell'")
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise TradeError("Quantity must be a number") from None
    if not quantity > 0 or quantity == float("inf"):
        raise TradeError("Quantity must be greater than 0")

    price = price_cache.get_price(ticker)
    if price is None:
        raise TradeError(f"No price available for {ticker}. Add it to the watchlist first.")

    with db.transaction() as conn:
        cash = db.get_cash_balance(conn=conn)
        position = db.get_position(ticker, conn=conn)
        held = position["quantity"] if position else 0.0

        if side == "buy":
            cost = quantity * price
            if cost > cash + 1e-9:
                raise TradeError(f"Insufficient cash: need {_money(cost)}, have {_money(cash)}")
            new_qty = held + quantity
            old_cost = position["avg_cost"] * held if position else 0.0
            avg_cost = (old_cost + cost) / new_qty
            db.set_cash_balance(cash - cost, conn=conn)
            db.upsert_position(ticker, new_qty, avg_cost, conn=conn)
        else:
            if quantity > held + QTY_EPSILON:
                raise TradeError(
                    f"Insufficient shares: trying to sell {_qty(quantity)} {ticker}, "
                    f"have {_qty(held)}"
                )
            remaining = held - quantity
            db.set_cash_balance(cash + quantity * price, conn=conn)
            if remaining <= QTY_EPSILON:
                db.delete_position(ticker, conn=conn)
            else:
                db.upsert_position(ticker, remaining, position["avg_cost"], conn=conn)

        trade = db.insert_trade(ticker, side, quantity, price, conn=conn)

    record_snapshot(price_cache)
    logger.info("Executed %s %s %s @ %.2f", side, quantity, ticker, price)
    return trade


def get_portfolio(price_cache: PriceCache) -> dict:
    """Cash, positions valued at cached prices (falling back to avg cost), and totals."""
    # Read cash and positions on one connection so a concurrent trade can't split them
    with db.transaction() as conn:
        cash = db.get_cash_balance(conn=conn)
        held = db.get_positions(conn=conn)
    positions = []
    positions_value = 0.0
    total_cost = 0.0
    for pos in held:
        qty = pos["quantity"]
        avg_cost = pos["avg_cost"]
        current = price_cache.get_price(pos["ticker"])
        if current is None:
            current = avg_cost
        market_value = qty * current
        cost_basis = qty * avg_cost
        pnl = market_value - cost_basis
        positions.append(
            {
                "ticker": pos["ticker"],
                "quantity": qty,
                "avg_cost": round(avg_cost, 4),
                "current_price": round(current, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_percent": round(pnl / cost_basis * 100, 2) if cost_basis else 0.0,
            }
        )
        positions_value += market_value
        total_cost += cost_basis
    return {
        "cash_balance": round(cash, 2),
        "total_value": round(cash + positions_value, 2),
        "positions_value": round(positions_value, 2),
        "unrealized_pnl": round(positions_value - total_cost, 2),
        "positions": positions,
    }


def record_snapshot(price_cache: PriceCache) -> float:
    """Persist the current total portfolio value and return it."""
    total = get_portfolio(price_cache)["total_value"]
    db.insert_snapshot(total)
    return total


def get_history() -> list[dict]:
    return db.get_snapshots()
