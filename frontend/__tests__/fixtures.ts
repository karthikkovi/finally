import type { Portfolio, PriceUpdate, WatchlistEntry } from "@/lib/types";

export function quote(ticker: string, price: number, timestamp = 1_700_000_000, prev = price): PriceUpdate {
  return {
    ticker,
    price,
    previous_price: prev,
    timestamp,
    change: price - prev,
    change_percent: prev ? ((price - prev) / prev) * 100 : 0,
    direction: price > prev ? "up" : price < prev ? "down" : "flat",
    open_price: prev,
    change_percent_open: 0.5,
  };
}

export function portfolio(): Portfolio {
  return {
    cash_balance: 5000,
    total_value: 5000 + 1900 + 1640,
    positions_value: 1900 + 1640,
    unrealized_pnl: 40,
    positions: [
      {
        ticker: "AAPL",
        quantity: 10,
        avg_cost: 190,
        current_price: 190,
        market_value: 1900,
        unrealized_pnl: 0,
        unrealized_pnl_percent: 0,
      },
      {
        ticker: "NVDA",
        quantity: 2,
        avg_cost: 800,
        current_price: 820,
        market_value: 1640,
        unrealized_pnl: 40,
        unrealized_pnl_percent: 2.5,
      },
    ],
  };
}

export function entry(ticker: string, price: number | null = null): WatchlistEntry {
  return {
    ticker,
    price,
    previous_price: price,
    change: price == null ? null : 0,
    change_percent: price == null ? null : 0,
    direction: price == null ? null : "flat",
    open_price: price,
    change_percent_open: price == null ? null : 0,
  };
}
