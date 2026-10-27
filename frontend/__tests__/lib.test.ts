import { describe, expect, it } from "vitest";
import { applyPriceEvent } from "@/hooks/usePriceStream";
import { normalizeActions } from "@/lib/api";
import { formatCurrency, formatPercent, formatPrice, formatSignedCurrency, trend } from "@/lib/format";
import { parseUtc, pnlSign, revaluePortfolio, snapshotsToPoints } from "@/lib/portfolio";
import { pnlColor, squarify } from "@/lib/treemap";
import { sparklinePath } from "@/components/charts/Sparkline";
import { toChartData } from "@/components/charts/TimeSeriesChart";
import { portfolio, quote } from "./fixtures";

describe("format", () => {
  it("formats currency, prices and percentages", () => {
    expect(formatCurrency(10000)).toBe("$10,000.00");
    expect(formatPrice(1234.5)).toBe("1234.50");
    expect(formatPrice(null)).toBe("—");
    expect(formatPercent(1.234)).toBe("+1.23%");
    expect(formatPercent(-0.5)).toBe("−0.50%");
    expect(formatSignedCurrency(-12.3)).toBe("−$12.30");
    expect(trend(0)).toBe("flat");
    expect(trend(-1)).toBe("down");
  });
});

describe("revaluePortfolio", () => {
  it("revalues positions and totals with live prices", () => {
    const live = revaluePortfolio(portfolio(), { AAPL: quote("AAPL", 200), NVDA: quote("NVDA", 700) });
    const aapl = live.positions.find((p) => p.ticker === "AAPL")!;
    expect(aapl.market_value).toBeCloseTo(2000);
    expect(aapl.unrealized_pnl).toBeCloseTo(100);
    expect(aapl.unrealized_pnl_percent).toBeCloseTo((100 / 1900) * 100);
    // 10 AAPL @ 200 + 2 NVDA @ 700
    expect(live.positions_value).toBeCloseTo(3400);
    expect(live.total_value).toBeCloseTo(5000 + 3400);
    expect(live.cost_basis).toBeCloseTo(1900 + 1600);
    expect(live.unrealized_pnl).toBeCloseTo(3400 - 3500);
  });

  it("falls back to the last known price when a ticker has no quote", () => {
    const live = revaluePortfolio(portfolio(), {});
    expect(live.positions.find((p) => p.ticker === "NVDA")!.current_price).toBe(820);
  });
});

describe("pnlSign / snapshots", () => {
  it("classifies P&L sign", () => {
    expect(pnlSign(0.01)).toBe("positive");
    expect(pnlSign(-0.01)).toBe("negative");
    expect(pnlSign(0)).toBe("flat");
  });

  it("treats offset-less timestamps as UTC", () => {
    expect(parseUtc("2026-01-01T00:00:00")).toBe(Date.UTC(2026, 0, 1));
    expect(parseUtc("2026-01-01T00:00:00+00:00")).toBe(Date.UTC(2026, 0, 1));
  });

  it("orders snapshots and keeps the last value per second", () => {
    const points = snapshotsToPoints([
      { total_value: 3, recorded_at: "2026-01-01T00:00:05.900Z" },
      { total_value: 1, recorded_at: "2026-01-01T00:00:01Z" },
      { total_value: 2, recorded_at: "2026-01-01T00:00:05.100Z" },
    ]);
    expect(points.map((p) => p.value)).toEqual([1, 2]);
  });
});

describe("treemap", () => {
  it("tiles the whole box with areas proportional to value", () => {
    const rects = squarify(
      [
        { value: 6, item: "a" },
        { value: 3, item: "b" },
        { value: 1, item: "c" },
        { value: 0, item: "dropped" },
      ],
      100,
      50,
    );
    expect(rects.map((r) => r.item)).toEqual(["a", "b", "c"]);
    const area = (item: string) => {
      const r = rects.find((x) => x.item === item)!;
      return r.w * r.h;
    };
    expect(area("a")).toBeCloseTo(3000);
    expect(area("b")).toBeCloseTo(1500);
    expect(area("c")).toBeCloseTo(500);
    for (const r of rects) {
      expect(r.x + r.w).toBeLessThanOrEqual(100.0001);
      expect(r.y + r.h).toBeLessThanOrEqual(50.0001);
    }
  });

  it("colors gains green, losses red, and zero neutral", () => {
    const rgb = (s: string) => s.match(/\d+/g)!.map(Number);
    const [ur, ug] = rgb(pnlColor(0.001));
    expect(ug).toBeGreaterThan(ur);
    const [dr, dg] = rgb(pnlColor(-0.001));
    expect(dr).toBeGreaterThan(dg);
    expect(pnlColor(0)).toBe("rgb(42, 50, 64)");
  });
});

describe("applyPriceEvent", () => {
  it("accumulates history with strictly increasing times and caps length", () => {
    let state = { prices: {}, history: {} };
    state = applyPriceEvent(state, { AAPL: quote("AAPL", 1, 10) }, 2);
    state = applyPriceEvent(state, { AAPL: quote("AAPL", 2, 10) }, 2); // same timestamp: price updates, no point
    state = applyPriceEvent(state, { AAPL: quote("AAPL", 3, 11) }, 2);
    state = applyPriceEvent(state, { AAPL: quote("AAPL", 4, 12) }, 2);
    expect((state.prices as Record<string, { price: number }>).AAPL.price).toBe(4);
    expect((state.history as Record<string, { value: number }[]>).AAPL.map((p) => p.value)).toEqual([3, 4]);
  });
});

describe("chart helpers", () => {
  it("collapses sub-second points for the chart", () => {
    const data = toChartData([
      { time: 10.1, value: 1 },
      { time: 10.6, value: 2 },
      { time: 11.2, value: 3 },
    ]);
    expect(data).toEqual([
      { time: 10, value: 2 },
      { time: 11, value: 3 },
    ]);
  });

  it("builds a sparkline path only with 2+ points", () => {
    expect(sparklinePath([{ time: 1, value: 1 }], 10, 10)).toBe("");
    expect(
      sparklinePath(
        [
          { time: 1, value: 1 },
          { time: 2, value: 2 },
        ],
        10,
        10,
      ),
    ).toMatch(/^M0\.0,8\.5L10\.0,1\.5$/);
  });
});

describe("normalizeActions", () => {
  it("accepts object and list forms", () => {
    const trade = { ticker: "AAPL", side: "buy", quantity: 1, status: "executed" };
    const watch = { ticker: "PYPL", action: "add", status: "applied" };
    expect(normalizeActions({ trades: [trade] })).toEqual({ trades: [trade], watchlist_changes: [] });
    expect(normalizeActions([trade, watch])).toEqual({ trades: [trade], watchlist_changes: [watch] });
    expect(normalizeActions(null)).toBeNull();
  });
});
