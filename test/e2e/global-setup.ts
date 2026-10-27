import type { FullConfig } from "@playwright/test";

/** Wait until the app answers /api/health, so the suite can start right after `docker compose up`. */
export default async function globalSetup(config: FullConfig) {
  const baseURL = (config.projects[0].use.baseURL as string) ?? "http://localhost:8000";
  const deadline = Date.now() + 120_000;
  let lastError: unknown;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseURL}/api/health`);
      if (res.ok) return;
      lastError = new Error(`health returned ${res.status}`);
    } catch (err) {
      lastError = err;
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`App at ${baseURL} not healthy after 120s: ${String(lastError)}`);
}
