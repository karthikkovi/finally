import { expect, test } from "@playwright/test";
import { DEFAULT_TICKERS, expectPricesMoving, getPortfolio, moneyOf, openApp } from "./helpers";

test.describe("Fresh start", () => {
  test("shows the default watchlist", async ({ page }) => {
    await openApp(page);
    for (const ticker of DEFAULT_TICKERS) {
      await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
    }
  });

  test("shows $10,000 cash on a fresh database, and header matches the API", async ({ page, request }) => {
    const before = await getPortfolio(request);
    await openApp(page);
    const cash = page.getByTestId("cash-balance");
    await expect(cash).toBeVisible();
    await expect(page.getByTestId("total-value")).toBeVisible();
    await expect.poll(() => moneyOf(cash)).toBeCloseTo(before.cash_balance, 2);

    // On a never-traded DB (docker test run, file runs first) the balance is the seeded $10k.
    test.skip(before.positions.length > 0 || before.cash_balance !== 10000, "DB is not fresh; $10k check skipped");
    await expect(cash).toHaveText(/\$10,000\.00/);
    await expect.poll(() => moneyOf(page.getByTestId("total-value"))).toBeCloseTo(10000, 2);
  });

  test("prices are streaming and changing", async ({ page }) => {
    await openApp(page);
    await expectPricesMoving(page);
  });

  test("price change applies a flash class", async ({ page }) => {
    await openApp(page);
    const cells = DEFAULT_TICKERS.map((t) => page.getByTestId(`watchlist-price-${t}`));
    // Some cell should carry an up/down flash class at some point while prices stream.
    await expect
      .poll(async () => {
        const classes = await Promise.all(cells.map((c) => c.getAttribute("class")));
        return classes.some((c) => /flash/i.test(c ?? ""));
      }, { timeout: 15_000, intervals: [100] })
      .toBe(true);
  });

  test("clicking a watchlist row selects it in the main chart", async ({ page }) => {
    await openApp(page);
    await page.getByTestId("watchlist-row-MSFT").click();
    await expect(page.getByTestId("main-chart")).toHaveAttribute("data-ticker", "MSFT");
    await page.getByTestId("watchlist-row-NVDA").click();
    await expect(page.getByTestId("main-chart")).toHaveAttribute("data-ticker", "NVDA");
  });
});
