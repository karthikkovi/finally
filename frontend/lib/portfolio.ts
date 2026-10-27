import type { Portfolio, Position, PriceUpdate } from "./types";

export interface LivePortfolio extends Portfolio {
  /** Sum of cost basis across positions. */
  cost_basis: number;
}

/**
 * Revalue the last-fetched portfolio with streaming prices so the header and
 * positions update every tick without refetching.
 */
export function revaluePortfolio(
  portfolio: Portfolio,
  prices: Record<string, PriceUpdate | undefined>,
): LivePortfolio {
  let positionsValue = 0;
  let costBasis = 0;
  const positions: Position[] = portfolio.positions.map((p) => {
    const current = prices[p.ticker]?.price ?? p.current_price;
    const marketValue = p.quantity * current;
    const cost = p.quantity * p.avg_cost;
    const pnl = marketValue - cost;
    positionsValue += marketValue;
    costBasis += cost;
    return {
      ...p,
      current_price: current,
      market_value: marketValue,
      unrealized_pnl: pnl,
      unrealized_pnl_percent: cost > 0 ? (pnl / cost) * 100 : 0,
    };
  });
  return {
    cash_balance: portfolio.cash_balance,
    positions,
    positions_value: positionsValue,
    total_value: portfolio.cash_balance + positionsValue,
    unrealized_pnl: positionsValue - costBasis,
    cost_basis: costBasis,
  };
}

export type PnlSign = "positive" | "negative" | "flat";

export function pnlSign(value: number): PnlSign {
  if (value > 1e-9) return "positive";
  if (value < -1e-9) return "negative";
  return "flat";
}

/** ISO snapshots → strictly increasing (unix seconds, value) points for charting. */
export function snapshotsToPoints(snapshots: { total_value: number; recorded_at: string }[]) {
  const bySecond = new Map<number, number>();
  for (const s of snapshots) {
    const t = Math.floor(parseUtc(s.recorded_at) / 1000);
    if (Number.isFinite(t)) bySecond.set(t, s.total_value);
  }
  return [...bySecond.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time, value }));
}

/** Parse an ISO timestamp, treating one without an offset as UTC (the backend's convention). */
export function parseUtc(iso: string): number {
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return Date.parse(hasZone ? iso : `${iso}Z`);
}
