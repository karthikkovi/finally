import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Workstation } from "@/components/Workstation";
import { entry, portfolio, quote } from "./fixtures";

vi.mock("@/components/charts/TimeSeriesChart", () => ({
  TimeSeriesChart: ({ data }: { data: unknown[] }) => <div data-testid="ts-chart" data-len={data.length} />,
}));

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  static CLOSED = 2;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  close() {
    this.readyState = 2;
  }
  open() {
    this.readyState = 1;
    this.onopen?.();
  }
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }
}

function json(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url === "/api/watchlist" && method === "GET") return json({ tickers: [entry("AAPL", 190), entry("NVDA", 820)] });
    if (url === "/api/portfolio") return json(portfolio());
    if (url === "/api/portfolio/history")
      return json({ snapshots: [{ total_value: 10000, recorded_at: "2026-01-01T00:00:00Z" }] });
    if (url === "/api/chat/history") return json({ messages: [] });
    if (url === "/api/portfolio/trade") {
      const next = portfolio();
      next.cash_balance = 4000;
      return json({
        trade: { id: "t", ticker: "AAPL", side: "buy", quantity: 5, price: 200, executed_at: "" },
        portfolio: next,
      });
    }
    return json({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Workstation", () => {
  it("loads data, streams prices into header and watchlist, and trades", async () => {
    render(<Workstation />);
    expect(await screen.findByTestId("watchlist-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("main-chart")).toHaveAttribute("data-ticker", "AAPL");
    await waitFor(() => expect(screen.getByTestId("cash-balance")).toHaveTextContent("$5,000.00"));
    expect(screen.getByTestId("pnl-chart")).toHaveAttribute("data-points", "1");

    const es = FakeEventSource.instances[0];
    expect(es.url).toBe("/api/stream/prices");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "reconnecting");
    act(() => {
      es.open();
      es.emit({ AAPL: quote("AAPL", 200, 1_700_000_001), NVDA: quote("NVDA", 800, 1_700_000_001) });
    });
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("200.00");
    // 5000 cash + 10×200 + 2×800
    expect(screen.getByTestId("total-value")).toHaveTextContent("$8,600.00");
    expect(screen.getByTestId("position-row-NVDA")).toHaveTextContent("$1,600.00");

    await userEvent.click(screen.getByTestId("watchlist-row-NVDA"));
    expect(screen.getByTestId("main-chart")).toHaveAttribute("data-ticker", "NVDA");
    expect(screen.getByTestId("trade-ticker")).toHaveValue("NVDA");

    await userEvent.clear(screen.getByTestId("trade-ticker"));
    await userEvent.type(screen.getByTestId("trade-ticker"), "aapl");
    await userEvent.type(screen.getByTestId("trade-quantity"), "5");
    await userEvent.click(screen.getByTestId("trade-buy"));
    await waitFor(() => expect(screen.getByTestId("cash-balance")).toHaveTextContent("$4,000.00"));
    const call = fetchMock.mock.calls.find(([u]) => u === "/api/portfolio/trade")!;
    expect(JSON.parse(call[1].body)).toEqual({ ticker: "AAPL", quantity: 5, side: "buy" });
  });

  it("marks the stream disconnected when the browser gives up, then retries", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      render(<Workstation />);
      const es = FakeEventSource.instances[0];
      act(() => {
        es.readyState = FakeEventSource.CLOSED;
        es.onerror?.();
      });
      expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "disconnected");
      await act(async () => {
        vi.advanceTimersByTime(3000);
      });
      expect(FakeEventSource.instances).toHaveLength(2);
      act(() => FakeEventSource.instances[1].open());
      expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
    } finally {
      vi.useRealTimers();
    }
  });

  it("follows the browser's offline/online events", () => {
    render(<Workstation />);
    act(() => FakeEventSource.instances[0].open());
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "disconnected");
    expect(FakeEventSource.instances[0].readyState).toBe(FakeEventSource.CLOSED);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "reconnecting");
    act(() => FakeEventSource.instances[1].open());
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "connected");
  });
});
