import { expect, test } from "@playwright/test";
import { addTicker, cleanupTicker, getPortfolio, getWatchlist, openApp, uniqueTicker, waitForPrice } from "./helpers";

// Requires LLM_MOCK=true on the server (see planning/TEAM.md, "LLM mock mode").
test.describe("AI chat (mock LLM)", () => {
  let ticker: string;

  test.beforeEach(() => {
    ticker = uniqueTicker();
  });

  test.afterEach(async ({ request }) => {
    await cleanupTicker(request, ticker);
  });

  async function send(page: import("@playwright/test").Page, text: string) {
    const responsePromise = page.waitForResponse((r) => r.url().endsWith("/api/chat") && r.request().method() === "POST");
    await page.getByTestId("chat-input").fill(text);
    await page.getByTestId("chat-send").click();
    return responsePromise;
  }

  test("plain message gets a mock response", async ({ page }) => {
    await openApp(page);
    await expect(page.getByTestId("chat-panel")).toBeVisible();
    const before = await page.locator('[data-testid="chat-message"][data-role="assistant"]').count();
    const res = await send(page, "How is my portfolio doing?");
    expect(res.status()).toBe(200);
    await expect(page.locator('[data-testid="chat-message"][data-role="user"]').last()).toContainText(
      "How is my portfolio doing?",
    );
    const assistant = page.locator('[data-testid="chat-message"][data-role="assistant"]');
    await expect(assistant).toHaveCount(before + 1);
    await expect(assistant.last()).toContainText("Mock response");
    await expect(page.getByTestId("chat-loading")).toHaveCount(0);
  });

  test("shows a loading indicator while waiting", async ({ page }) => {
    await openApp(page);
    // Delay the chat response so the indicator is observable.
    await page.route("**/api/chat", async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await page.getByTestId("chat-input").fill("hello");
    await page.getByTestId("chat-send").click();
    await expect(page.getByTestId("chat-loading")).toBeVisible();
    await expect(page.getByTestId("chat-loading")).toHaveCount(0, { timeout: 15_000 });
  });

  test("'buy 2 <TICKER>' executes a trade shown inline and the position appears", async ({ page, request }) => {
    await addTicker(request, ticker);
    await waitForPrice(request, ticker);
    const cashBefore = (await getPortfolio(request)).cash_balance;
    await openApp(page);

    const res = await send(page, `buy 2 ${ticker}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.trades).toHaveLength(1);
    expect(body.trades[0]).toMatchObject({ ticker, side: "buy", quantity: 2, status: "executed" });

    await expect(page.locator('[data-testid="chat-message"][data-role="assistant"]').last()).toContainText(/mock/i);
    await expect(page.getByTestId("chat-action").filter({ hasText: ticker }).last()).toBeVisible();
    await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();

    const after = await getPortfolio(request);
    expect(after.positions.find((p) => p.ticker === ticker)?.quantity).toBe(2);
    expect(after.cash_balance).toBeCloseTo(cashBefore - body.trades[0].price * 2, 1);
  });

  test("'add <TICKER>' adds it to the watchlist", async ({ page, request }) => {
    await openApp(page);
    const res = await send(page, `add ${ticker}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.watchlist_changes[0]).toMatchObject({ ticker, action: "add", status: "applied" });
    await expect(page.getByTestId("chat-action").filter({ hasText: ticker }).last()).toBeVisible();
    await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
    expect((await getWatchlist(request)).map((t) => t.ticker)).toContain(ticker);
  });

  test("failed trade is reported inline", async ({ page }) => {
    await openApp(page);
    // Sell of a ticker we never held must fail validation.
    const res = await send(page, `sell 5 ${ticker}`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.trades[0]).toMatchObject({ ticker, side: "sell", status: "failed" });
    expect(body.trades[0].error).toBeTruthy();
    await expect(page.getByTestId("chat-action").filter({ hasText: ticker }).last()).toBeVisible();
  });
});
