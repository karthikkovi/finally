import { expect, test } from "@playwright/test";
import { getWatchlist, openApp, removeTicker, uniqueTicker } from "./helpers";

test.describe("Watchlist management", () => {
  let ticker: string;

  test.beforeEach(() => {
    ticker = uniqueTicker();
  });

  test.afterEach(async ({ request }) => {
    await removeTicker(request, ticker);
  });

  test("add a ticker via the UI, see it stream, then remove it", async ({ page, request }) => {
    await openApp(page);

    await page.getByTestId("watchlist-add-input").fill(ticker.toLowerCase());
    await page.getByTestId("watchlist-add-button").click();

    const row = page.getByTestId(`watchlist-row-${ticker}`);
    await expect(row).toBeVisible();
    await expect(page.getByTestId(`watchlist-price-${ticker}`)).toHaveText(/\d/, { timeout: 15_000 });
    expect((await getWatchlist(request)).map((t) => t.ticker)).toContain(ticker);

    await page.getByTestId(`watchlist-remove-${ticker}`).click();
    await expect(row).toHaveCount(0);
    await expect.poll(async () => (await getWatchlist(request)).map((t) => t.ticker)).not.toContain(ticker);

    // Removal persists across reload.
    await page.reload();
    await expect(page.getByTestId("watchlist-row-AAPL")).toBeVisible();
    await expect(page.getByTestId(`watchlist-row-${ticker}`)).toHaveCount(0);
  });

  test("ticker added via the API appears after reload", async ({ page, request }) => {
    const res = await request.post("/api/watchlist", { data: { ticker } });
    expect(res.status()).toBe(201);
    await openApp(page);
    await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
  });
});
