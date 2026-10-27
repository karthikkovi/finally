import { expect, test, type Page } from "@playwright/test";
import {
  addTicker,
  cleanupTicker,
  getPortfolio,
  moneyOf,
  openApp,
  trade,
  uniqueTicker,
  waitForPrice,
} from "./helpers";

async function submitTrade(page: Page, ticker: string, quantity: number, side: "buy" | "sell") {
  await page.getByTestId("trade-ticker").fill(ticker);
  await page.getByTestId("trade-quantity").fill(String(quantity));
  const responsePromise = page.waitForResponse(
    (r) => r.url().includes("/api/portfolio/trade") && r.request().method() === "POST",
  );
  await page.getByTestId(side === "buy" ? "trade-buy" : "trade-sell").click();
  const response = await responsePromise;
  return { status: response.status(), body: await response.json() };
}

test.describe("Trading", () => {
  let ticker: string;

  test.beforeEach(async ({ request }) => {
    ticker = uniqueTicker();
    await addTicker(request, ticker);
    await waitForPrice(request, ticker);
  });

  test.afterEach(async ({ request }) => {
    await cleanupTicker(request, ticker);
  });

  test("buy shares: cash decreases, position and heatmap cell appear", async ({ page, request }) => {
    const before = await getPortfolio(request);
    await openApp(page);

    const { status, body } = await submitTrade(page, ticker, 2, "buy");
    expect(status).toBe(200);
    expect(body.trade).toMatchObject({ ticker, side: "buy", quantity: 2 });
    const expectedCash = before.cash_balance - body.trade.price * 2;
    expect(body.portfolio.cash_balance).toBeCloseTo(expectedCash, 1);

    await expect.poll(() => moneyOf(page.getByTestId("cash-balance"))).toBeCloseTo(expectedCash, 1);
    const row = page.getByTestId(`position-row-${ticker}`);
    await expect(row).toBeVisible();
    await expect(row).toContainText(ticker);
    await expect(row).toContainText("2");
    await expect(page.getByTestId(`heatmap-cell-${ticker}`)).toBeVisible();

    const after = await getPortfolio(request);
    expect(after.positions.find((p) => p.ticker === ticker)?.quantity).toBe(2);
  });

  test("sell shares: cash increases, position updates then disappears", async ({ page, request }) => {
    await trade(request, ticker, "buy", 3);
    await openApp(page);
    const row = page.getByTestId(`position-row-${ticker}`);
    await expect(row).toBeVisible();

    const cashBefore = (await getPortfolio(request)).cash_balance;
    const partial = await submitTrade(page, ticker, 1, "sell");
    expect(partial.status).toBe(200);
    const cashAfterPartial = cashBefore + partial.body.trade.price * 1;
    expect(partial.body.portfolio.cash_balance).toBeCloseTo(cashAfterPartial, 1);
    await expect.poll(() => moneyOf(page.getByTestId("cash-balance"))).toBeCloseTo(cashAfterPartial, 1);
    expect((await getPortfolio(request)).positions.find((p) => p.ticker === ticker)?.quantity).toBe(2);
    await expect(row).toBeVisible();

    const full = await submitTrade(page, ticker, 2, "sell");
    expect(full.status).toBe(200);
    await expect(row).toHaveCount(0);
    await expect(page.getByTestId(`heatmap-cell-${ticker}`)).toHaveCount(0);
    expect((await getPortfolio(request)).positions.find((p) => p.ticker === ticker)).toBeUndefined();
    await expect
      .poll(() => moneyOf(page.getByTestId("cash-balance")))
      .toBeCloseTo(cashAfterPartial + full.body.trade.price * 2, 1);
  });

  test("selling more than owned shows a trade error and changes nothing", async ({ page, request }) => {
    const before = await getPortfolio(request);
    await openApp(page);
    const { status } = await submitTrade(page, ticker, 5, "sell");
    expect(status).toBe(400);
    await expect(page.getByTestId("trade-error")).toBeVisible();
    await expect(page.getByTestId("trade-error")).not.toBeEmpty();
    expect((await getPortfolio(request)).cash_balance).toBeCloseTo(before.cash_balance, 2);
  });

  test("buying with insufficient cash shows a trade error", async ({ page }) => {
    await openApp(page);
    const { status } = await submitTrade(page, ticker, 10_000_000, "buy");
    expect(status).toBe(400);
    await expect(page.getByTestId("trade-error")).toBeVisible();
    await expect(page.getByTestId("trade-error")).toContainText(/cash/i);
  });
});
