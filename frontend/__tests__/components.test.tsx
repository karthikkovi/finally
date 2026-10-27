import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Header } from "@/components/Header";
import { Heatmap } from "@/components/Heatmap";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeBar } from "@/components/TradeBar";
import { FlashingPrice, Watchlist } from "@/components/Watchlist";
import { ApiError } from "@/lib/api";
import { entry, portfolio, quote } from "./fixtures";

describe("Header", () => {
  it("shows totals and connection status", () => {
    render(<Header totalValue={10000} cashBalance={2500.5} unrealizedPnl={-12} costBasis={100} status="reconnecting" />);
    expect(screen.getByTestId("total-value")).toHaveTextContent("$10,000.00");
    expect(screen.getByTestId("cash-balance")).toHaveTextContent("$2,500.50");
    expect(screen.getByTestId("connection-status")).toHaveAttribute("data-status", "reconnecting");
  });
});

describe("FlashingPrice", () => {
  it("flashes up/down on price changes and clears after the animation", () => {
    const { rerender } = render(<FlashingPrice ticker="AAPL" price={100} />);
    const cell = () => screen.getByTestId("watchlist-price-AAPL");
    expect(cell()).toHaveTextContent("100.00");
    expect(cell().className).not.toMatch(/flash/);

    rerender(<FlashingPrice ticker="AAPL" price={101} />);
    expect(cell()).toHaveClass("flash-up");
    expect(cell()).toHaveTextContent("101.00");

    rerender(<FlashingPrice ticker="AAPL" price={99} />);
    expect(cell()).toHaveClass("flash-down");

    // jsdom lacks CSS animations, so React may listen for the prefixed event name.
    act(() => {
      cell().dispatchEvent(new Event("animationend", { bubbles: true }));
      cell().dispatchEvent(new Event("webkitAnimationEnd", { bubbles: true }));
    });
    expect(cell().className).not.toMatch(/flash/);
  });

  it("does not flash on the first price", () => {
    const { rerender } = render(<FlashingPrice ticker="AAPL" price={null} />);
    rerender(<FlashingPrice ticker="AAPL" price={50} />);
    expect(screen.getByTestId("watchlist-price-AAPL").className).not.toMatch(/flash/);
  });
});

describe("Watchlist", () => {
  function setup(overrides: Partial<React.ComponentProps<typeof Watchlist>> = {}) {
    const props = {
      entries: [entry("AAPL", 190), entry("TSLA")],
      prices: { AAPL: quote("AAPL", 191.25) },
      history: {},
      selected: "AAPL",
      onSelect: vi.fn(),
      onAdd: vi.fn().mockResolvedValue(undefined),
      onRemove: vi.fn().mockResolvedValue(undefined),
      ...overrides,
    };
    render(<Watchlist {...props} />);
    return props;
  }

  it("renders rows with live prices, falling back to REST prices", () => {
    setup();
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("191.25");
    expect(screen.getByTestId("watchlist-price-TSLA")).toHaveTextContent("—");
    expect(screen.getByTestId("watchlist-row-AAPL")).toHaveTextContent("+0.50%");
  });

  it("selects a ticker on row click", async () => {
    const props = setup();
    await userEvent.click(screen.getByTestId("watchlist-row-TSLA"));
    expect(props.onSelect).toHaveBeenCalledWith("TSLA");
  });

  it("adds an upper-cased ticker and removes one", async () => {
    const props = setup();
    await userEvent.type(screen.getByTestId("watchlist-add-input"), " pypl ");
    await userEvent.click(screen.getByTestId("watchlist-add-button"));
    expect(props.onAdd).toHaveBeenCalledWith("PYPL");
    await waitFor(() => expect(screen.getByTestId("watchlist-add-input")).toHaveValue(""));

    await userEvent.click(screen.getByTestId("watchlist-remove-TSLA"));
    expect(props.onRemove).toHaveBeenCalledWith("TSLA");
    expect(props.onSelect).not.toHaveBeenCalled();
  });

  it("shows add errors", async () => {
    setup({ onAdd: vi.fn().mockRejectedValue(new ApiError("Ticker already on watchlist", 409)) });
    await userEvent.type(screen.getByTestId("watchlist-add-input"), "AAPL");
    await userEvent.click(screen.getByTestId("watchlist-add-button"));
    expect(await screen.findByRole("alert")).toHaveTextContent("already on watchlist");
  });
});

describe("Heatmap", () => {
  it("renders a cell per position with P&L sign and color", () => {
    const p = portfolio();
    p.positions[0].unrealized_pnl = -5;
    p.positions[0].unrealized_pnl_percent = -0.3;
    render(<Heatmap positions={p.positions} size={{ width: 400, height: 200 }} />);
    const nvda = screen.getByTestId("heatmap-cell-NVDA");
    const aapl = screen.getByTestId("heatmap-cell-AAPL");
    expect(nvda).toHaveAttribute("data-pnl", "positive");
    expect(aapl).toHaveAttribute("data-pnl", "negative");
    const [r, g] = nvda.style.backgroundColor.match(/\d+/g)!.map(Number);
    expect(g).toBeGreaterThan(r);
    // AAPL has the larger market value, so the larger tile.
    expect(parseFloat(aapl.style.width) * parseFloat(aapl.style.height)).toBeGreaterThan(
      parseFloat(nvda.style.width) * parseFloat(nvda.style.height),
    );
  });

  it("shows an empty state", () => {
    render(<Heatmap positions={[]} size={{ width: 400, height: 200 }} />);
    expect(screen.getByTestId("heatmap")).toHaveTextContent("No positions yet");
  });
});

describe("PositionsTable", () => {
  it("lists positions with fixed-precision avg cost and signed P&L", () => {
    render(<PositionsTable positions={portfolio().positions} />);
    const row = screen.getByTestId("position-row-NVDA");
    expect(row).toHaveTextContent("800.00");
    expect(row).toHaveTextContent("+$40.00");
    expect(row).toHaveTextContent("+2.50%");
    expect(screen.getByTestId("position-row-AAPL")).toHaveTextContent("10");
  });
});

describe("TradeBar", () => {
  function setup(onTrade = vi.fn()) {
    const onTickerChange = vi.fn();
    render(<TradeBar ticker="AAPL" onTickerChange={onTickerChange} price={190} onTrade={onTrade} />);
    return { onTrade, onTickerChange };
  }

  it("submits a buy and confirms the fill", async () => {
    const onTrade = vi.fn().mockResolvedValue({
      id: "t1",
      ticker: "AAPL",
      side: "buy",
      quantity: 2,
      price: 190.5,
      executed_at: "",
    });
    setup(onTrade);
    await userEvent.type(screen.getByTestId("trade-quantity"), "2");
    expect(screen.getByText(/est\./)).toHaveTextContent("$380.00");
    await userEvent.click(screen.getByTestId("trade-buy"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 2, "buy");
    expect(await screen.findByText(/Bought 2 AAPL/)).toBeInTheDocument();
    expect(screen.queryByTestId("trade-error")).toBeNull();
  });

  it("shows server errors", async () => {
    setup(vi.fn().mockRejectedValue(new ApiError("Insufficient shares: have 0, need 5", 400)));
    await userEvent.type(screen.getByTestId("trade-quantity"), "5");
    await userEvent.click(screen.getByTestId("trade-sell"));
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient shares");
  });

  it("validates quantity locally", async () => {
    const { onTrade } = setup();
    await userEvent.click(screen.getByTestId("trade-buy"));
    expect(screen.getByTestId("trade-error")).toHaveTextContent("quantity");
    expect(onTrade).not.toHaveBeenCalled();
  });

  it("upper-cases the ticker as typed", async () => {
    const { onTickerChange } = setup();
    await act(async () => {
      fireEvent.change(screen.getByTestId("trade-ticker"), { target: { value: "msft" } });
    });
    expect(onTickerChange).toHaveBeenCalledWith("MSFT");
  });
});
