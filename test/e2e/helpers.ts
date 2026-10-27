import { expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";

export const DEFAULT_TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"];

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
}

export interface Portfolio {
  cash_balance: number;
  total_value: number;
  positions_value: number;
  unrealized_pnl: number;
  positions: Position[];
}

export interface WatchlistEntry {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  change: number | null;
  change_percent: number | null;
  direction: string | null;
  open_price: number | null;
  change_percent_open: number | null;
}

/** A ticker that no other test (or prior run) is using: "ZZ" + 3 random letters. */
export function uniqueTicker(): string {
  const letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  let s = "ZZ";
  for (let i = 0; i < 3; i++) s += letters[Math.floor(Math.random() * letters.length)];
  return s;
}

/** Parse "$10,000.00" / "-$12.34" / "(12.34)" into a number. */
export function parseMoney(text: string | null): number {
  if (!text) return NaN;
  const negative = /-|\(/.test(text);
  const n = parseFloat(text.replace(/[^0-9.]/g, ""));
  return negative ? -n : n;
}

export async function getPortfolio(request: APIRequestContext): Promise<Portfolio> {
  const res = await request.get("/api/portfolio");
  expect(res.status()).toBe(200);
  return res.json();
}

export async function getWatchlist(request: APIRequestContext): Promise<WatchlistEntry[]> {
  const res = await request.get("/api/watchlist");
  expect(res.status()).toBe(200);
  return (await res.json()).tickers;
}

export async function addTicker(request: APIRequestContext, ticker: string) {
  const res = await request.post("/api/watchlist", { data: { ticker } });
  expect([201, 409]).toContain(res.status());
}

export async function removeTicker(request: APIRequestContext, ticker: string) {
  await request.delete(`/api/watchlist/${ticker}`);
}

/** Poll the watchlist until the ticker has a live price; returns that price. */
export async function waitForPrice(request: APIRequestContext, ticker: string): Promise<number> {
  let price: number | null = null;
  await expect
    .poll(
      async () => {
        const entry = (await getWatchlist(request)).find((t) => t.ticker === ticker);
        price = entry?.price ?? null;
        return price;
      },
      { message: `waiting for a price for ${ticker}`, timeout: 20_000 },
    )
    .not.toBeNull();
  return price as unknown as number;
}

export async function trade(request: APIRequestContext, ticker: string, side: "buy" | "sell", quantity: number) {
  const res = await request.post("/api/portfolio/trade", { data: { ticker, side, quantity } });
  expect(res.status(), await res.text()).toBe(200);
  return res.json();
}

/** Sell any shares held in `ticker` and drop it from the watchlist. Best-effort cleanup. */
export async function cleanupTicker(request: APIRequestContext, ticker: string) {
  const res = await request.get("/api/portfolio");
  if (res.ok()) {
    const pos = ((await res.json()) as Portfolio).positions.find((p) => p.ticker === ticker);
    if (pos && pos.quantity > 0) {
      await request.post("/api/portfolio/trade", { data: { ticker, side: "sell", quantity: pos.quantity } });
    }
  }
  await removeTicker(request, ticker);
}

export async function moneyOf(locator: Locator): Promise<number> {
  return parseMoney(await locator.textContent());
}

/** Open the app and wait until the price stream is connected. */
export async function openApp(page: Page) {
  await page.goto("/");
  await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected", { timeout: 20_000 });
}

/** Assert that at least one default ticker's displayed price changes within the timeout. */
export async function expectPricesMoving(page: Page, timeout = 15_000) {
  const cells = DEFAULT_TICKERS.map((t) => page.getByTestId(`watchlist-price-${t}`));
  await expect(cells[0]).toHaveText(/\d/, { timeout });
  const initial = await Promise.all(cells.map((c) => c.textContent()));
  await expect
    .poll(async () => {
      const now = await Promise.all(cells.map((c) => c.textContent()));
      return now.some((text, i) => text !== initial[i]);
    }, { message: "expected at least one watchlist price to change", timeout })
    .toBe(true);
}
