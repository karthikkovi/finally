import { expect, test } from "@playwright/test";
import {
  addTicker,
  cleanupTicker,
  DEFAULT_TICKERS,
  getPortfolio,
  getWatchlist,
  trade,
  uniqueTicker,
  waitForPrice,
} from "./helpers";

test.describe("REST API", () => {
  test("GET /api/health", async ({ request }) => {
    const res = await request.get("/api/health");
    expect(res.status()).toBe(200);
    expect(await res.json()).toEqual({ status: "ok" });
  });

  test("GET /api/portfolio shape", async ({ request }) => {
    const p = await getPortfolio(request);
    for (const key of ["cash_balance", "total_value", "positions_value", "unrealized_pnl"] as const) {
      expect(typeof p[key], key).toBe("number");
    }
    expect(Array.isArray(p.positions)).toBe(true);
    expect(p.total_value).toBeCloseTo(p.cash_balance + p.positions_value, 1);
  });

  test("GET /api/watchlist includes defaults with live prices", async ({ request }) => {
    const tickers = await getWatchlist(request);
    const symbols = tickers.map((t) => t.ticker);
    for (const t of DEFAULT_TICKERS) expect(symbols).toContain(t);
    const aapl = await waitForPrice(request, "AAPL");
    expect(aapl).toBeGreaterThan(0);
    const entry = (await getWatchlist(request)).find((t) => t.ticker === "AAPL")!;
    for (const key of ["price", "previous_price", "change", "change_percent", "open_price", "change_percent_open"]) {
      expect(typeof (entry as any)[key], key).toBe("number");
    }
    expect(["up", "down", "flat"]).toContain(entry.direction);
  });

  test("GET /api/portfolio/history shape", async ({ request }) => {
    const res = await request.get("/api/portfolio/history");
    expect(res.status()).toBe(200);
    const { snapshots } = await res.json();
    expect(Array.isArray(snapshots)).toBe(true);
    for (const s of snapshots.slice(0, 5)) {
      expect(typeof s.total_value).toBe("number");
      expect(typeof s.recorded_at).toBe("string");
    }
  });

  test.describe("watchlist errors", () => {
    test("invalid ticker is 400", async ({ request }) => {
      for (const bad of ["", "TOO-LONG-TICKER!", "12$"]) {
        const res = await request.post("/api/watchlist", { data: { ticker: bad } });
        expect(res.status(), `ticker ${JSON.stringify(bad)}`).toBe(400);
        expect(typeof (await res.json()).detail).toBe("string");
      }
    });

    test("duplicate is 409, delete is 204 then 404", async ({ request }) => {
      const ticker = uniqueTicker();
      try {
        const created = await request.post("/api/watchlist", { data: { ticker: ticker.toLowerCase() } });
        expect(created.status()).toBe(201);
        expect(await created.json()).toEqual({ ticker });
        const dup = await request.post("/api/watchlist", { data: { ticker } });
        expect(dup.status()).toBe(409);
        const del = await request.delete(`/api/watchlist/${ticker}`);
        expect(del.status()).toBe(204);
        const again = await request.delete(`/api/watchlist/${ticker}`);
        expect(again.status()).toBe(404);
      } finally {
        await cleanupTicker(request, ticker);
      }
    });
  });

  test.describe("trades", () => {
    let ticker: string;

    test.beforeEach(async ({ request }) => {
      ticker = uniqueTicker();
      await addTicker(request, ticker);
      await waitForPrice(request, ticker);
    });

    test.afterEach(async ({ request }) => {
      await cleanupTicker(request, ticker);
    });

    test("buy then sell round-trip: response shape, avg cost, cash math", async ({ request }) => {
      const cash0 = (await getPortfolio(request)).cash_balance;
      const b1 = await trade(request, ticker, "buy", 1.5);
      expect(b1.trade).toMatchObject({ ticker, side: "buy", quantity: 1.5 });
      for (const k of ["id", "price", "executed_at"]) expect(b1.trade[k], k).toBeDefined();
      expect(b1.portfolio.cash_balance).toBeCloseTo(cash0 - 1.5 * b1.trade.price, 1);

      const b2 = await trade(request, ticker, "buy", 0.5);
      const pos = b2.portfolio.positions.find((p: any) => p.ticker === ticker);
      expect(pos.quantity).toBeCloseTo(2, 6);
      expect(pos.avg_cost).toBeCloseTo((1.5 * b1.trade.price + 0.5 * b2.trade.price) / 2, 4);
      for (const k of ["current_price", "market_value", "unrealized_pnl", "unrealized_pnl_percent"]) {
        expect(typeof pos[k], k).toBe("number");
      }

      const s = await trade(request, ticker, "sell", 2);
      expect(s.portfolio.positions.find((p: any) => p.ticker === ticker)).toBeUndefined();
      expect(s.portfolio.cash_balance).toBeCloseTo(
        cash0 - 1.5 * b1.trade.price - 0.5 * b2.trade.price + 2 * s.trade.price,
        1,
      );
    });

    test("validation failures are 400 with detail and change nothing", async ({ request }) => {
      const before = await getPortfolio(request);
      const cases = [
        { ticker, side: "buy", quantity: 0 },
        { ticker, side: "buy", quantity: -1 },
        { ticker, side: "sell", quantity: 1 }, // not held
        { ticker, side: "buy", quantity: 1e9 }, // insufficient cash
      ];
      for (const data of cases) {
        const res = await request.post("/api/portfolio/trade", { data });
        expect([400, 422], JSON.stringify(data)).toContain(res.status());
        expect((await res.json()).detail, JSON.stringify(data)).toBeTruthy();
      }
      const after = await getPortfolio(request);
      expect(after.cash_balance).toBeCloseTo(before.cash_balance, 2);
      expect(after.positions.find((p) => p.ticker === ticker)).toBeUndefined();
    });

    test("insufficient cash and oversell are exactly 400", async ({ request }) => {
      const r1 = await request.post("/api/portfolio/trade", { data: { ticker, side: "buy", quantity: 1e9 } });
      expect(r1.status()).toBe(400);
      expect((await r1.json()).detail).toMatch(/cash/i);
      const r2 = await request.post("/api/portfolio/trade", { data: { ticker, side: "sell", quantity: 1 } });
      expect(r2.status()).toBe(400);
    });

    test("bad side is rejected", async ({ request }) => {
      const res = await request.post("/api/portfolio/trade", { data: { ticker, side: "short", quantity: 1 } });
      expect([400, 422]).toContain(res.status());
    });
  });

  test.describe("chat (mock)", () => {
    test("POST /api/chat plain message shape", async ({ request }) => {
      const res = await request.post("/api/chat", { data: { message: "hello there" } });
      expect(res.status()).toBe(200);
      const body = await res.json();
      expect(body.message).toBe("Mock response: I can help you analyze your portfolio.");
      expect(body.trades ?? []).toEqual([]);
      expect(body.watchlist_changes ?? []).toEqual([]);
    });

    test("chat history records user and assistant messages", async ({ request }) => {
      const marker = `history check ${Date.now()}`;
      await request.post("/api/chat", { data: { message: marker } });
      const res = await request.get("/api/chat/history");
      expect(res.status()).toBe(200);
      const { messages } = await res.json();
      const idx = messages.findIndex((m: any) => m.role === "user" && m.content === marker);
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(messages[idx + 1]?.role).toBe("assistant");
      for (const k of ["id", "role", "content", "created_at"]) expect(messages[idx][k], k).toBeDefined();
    });

    test("mock trade command executes through the real trade path", async ({ request }) => {
      const ticker = uniqueTicker();
      try {
        await addTicker(request, ticker);
        await waitForPrice(request, ticker);
        const res = await request.post("/api/chat", { data: { message: `BUY 3 ${ticker.toLowerCase()}` } });
        const body = await res.json();
        expect(body.trades).toHaveLength(1);
        expect(body.trades[0]).toMatchObject({ ticker, side: "buy", quantity: 3, status: "executed" });
        expect((await getPortfolio(request)).positions.find((p) => p.ticker === ticker)?.quantity).toBe(3);
      } finally {
        await cleanupTicker(request, ticker);
      }
    });
  });

  test("SSE /api/stream/prices emits JSON price events", async ({ baseURL }) => {
    const controller = new AbortController();
    const res = await fetch(`${baseURL}/api/stream/prices`, { signal: controller.signal });
    try {
      expect(res.status).toBe(200);
      expect(res.headers.get("content-type")).toContain("text/event-stream");
      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      const deadline = Date.now() + 10_000;
      let payload: any = null;
      while (!payload && Date.now() < deadline) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const m = buf.match(/^data: (.+)$/m);
        if (m) payload = JSON.parse(m[1]);
      }
      expect(buf).toMatch(/retry: ?1000/);
      expect(payload).not.toBeNull();
      expect(payload.AAPL).toMatchObject({ ticker: "AAPL" });
      for (const k of ["price", "previous_price", "timestamp", "change", "change_percent", "open_price", "change_percent_open"]) {
        expect(typeof payload.AAPL[k], k).toBe("number");
      }
      expect(["up", "down", "flat"]).toContain(payload.AAPL.direction);
    } finally {
      controller.abort();
    }
  });
});
