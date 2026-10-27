import { expect, test } from "@playwright/test";
import { addTicker, cleanupTicker, getPortfolio, openApp, trade, uniqueTicker, waitForPrice } from "./helpers";

function rgb(color: string): [number, number, number] | null {
  const m = color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

test.describe("Portfolio visualizations", () => {
  let ticker: string;

  test.beforeEach(async ({ request }) => {
    ticker = uniqueTicker();
    await addTicker(request, ticker);
    await waitForPrice(request, ticker);
    await trade(request, ticker, "buy", 1);
  });

  test.afterEach(async ({ request }) => {
    await cleanupTicker(request, ticker);
  });

  test("heatmap cell is colored by P&L sign", async ({ page }) => {
    await openApp(page);
    const cell = page.getByTestId(`heatmap-cell-${ticker}`);
    await expect(cell).toBeVisible();
    await expect(cell).toHaveAttribute("data-pnl", /^(positive|negative|flat)$/);

    // Wait for the price to move away from cost so the cell is green or red, then check the actual color.
    await expect
      .poll(async () => cell.getAttribute("data-pnl"), { timeout: 20_000 })
      .toMatch(/^(positive|negative)$/);
    const { pnl, color } = await cell.evaluate((el) => {
      // The fill may be on the cell itself or a child (e.g. SVG rect); take the first non-transparent one.
      const nodes = [el, ...Array.from(el.querySelectorAll("*"))];
      for (const n of nodes) {
        const s = getComputedStyle(n);
        for (const c of [s.backgroundColor, s.fill]) {
          if (c && c !== "none" && !/rgba\(0,\s*0,\s*0,\s*0\)|transparent/.test(c)) {
            return { pnl: el.getAttribute("data-pnl"), color: c };
          }
        }
      }
      return { pnl: el.getAttribute("data-pnl"), color: "" };
    });
    const c = rgb(color);
    expect(c, `heatmap cell color "${color}" should be an rgb color`).not.toBeNull();
    const [r, g] = c!;
    if (pnl === "positive") expect(g, `positive cell should be green-ish, got ${color}`).toBeGreaterThan(r);
    else expect(r, `negative cell should be red-ish, got ${color}`).toBeGreaterThan(g);
  });

  test("heatmap data-pnl agrees with API P&L sign", async ({ page, request }) => {
    await openApp(page);
    const cell = page.getByTestId(`heatmap-cell-${ticker}`);
    await expect(cell).toBeVisible();
    // Prices tick, so allow a few attempts to sample a consistent snapshot.
    await expect
      .poll(async () => {
        const pos = (await getPortfolio(request)).positions.find((p) => p.ticker === ticker)!;
        const expected = pos.unrealized_pnl > 0 ? "positive" : pos.unrealized_pnl < 0 ? "negative" : "flat";
        return (await cell.getAttribute("data-pnl")) === expected;
      }, { timeout: 20_000, intervals: [200] })
      .toBe(true);
  });

  test("P&L chart has data points", async ({ page, request }) => {
    // A trade records a snapshot immediately, so history is non-empty.
    const res = await request.get("/api/portfolio/history");
    expect(res.status()).toBe(200);
    const { snapshots } = await res.json();
    expect(snapshots.length).toBeGreaterThan(0);

    await openApp(page);
    const chart = page.getByTestId("pnl-chart");
    await expect(chart).toBeVisible();
    await expect.poll(async () => Number(await chart.getAttribute("data-points"))).toBeGreaterThan(0);
  });

  test("positions table shows the position's columns", async ({ page, request }) => {
    await openApp(page);
    await expect(page.getByTestId("positions-table")).toBeVisible();
    const row = page.getByTestId(`position-row-${ticker}`);
    await expect(row).toBeVisible();
    const pos = (await getPortfolio(request)).positions.find((p) => p.ticker === ticker)!;
    await expect(row).toContainText(ticker);
    // avg cost is fixed, so it must appear verbatim (2dp).
    await expect(row).toContainText(pos.avg_cost.toFixed(2));
  });
});
