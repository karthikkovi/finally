import { expect, test } from "@playwright/test";
import { expectPricesMoving, openApp } from "./helpers";

test.describe("SSE resilience", () => {
  test("status goes non-connected when the stream drops and recovers afterwards", async ({ page, context }) => {
    await openApp(page);
    const status = page.getByTestId("connection-status");

    // Cut the network: kills the live EventSource and makes reconnect attempts fail.
    await page.route("**/api/stream/prices", (route) => route.abort("internetdisconnected"));
    await context.setOffline(true);
    await expect(status).toHaveAttribute("data-status", /^(reconnecting|disconnected)$/, { timeout: 15_000 });

    // Restore: EventSource retries (server sends retry: 1000) and should reconnect on its own.
    await context.setOffline(false);
    await page.unroute("**/api/stream/prices");
    await expect(status).toHaveAttribute("data-status", "connected", { timeout: 30_000 });

    // And prices keep flowing after the reconnect.
    await expectPricesMoving(page);
  });

  test("status reflects a stream that fails from the start", async ({ page }) => {
    await page.route("**/api/stream/prices", (route) => route.abort("connectionrefused"));
    await page.goto("/");
    await expect(page.getByTestId("connection-status")).toHaveAttribute(
      "data-status",
      /^(reconnecting|disconnected)$/,
      { timeout: 15_000 },
    );
    await page.unroute("**/api/stream/prices");
    await expect(page.getByTestId("connection-status")).toHaveAttribute("data-status", "connected", {
      timeout: 30_000,
    });
  });
});
