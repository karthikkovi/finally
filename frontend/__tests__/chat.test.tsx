import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPanel } from "@/components/ChatPanel";
import { api } from "@/lib/api";
import type { ChatResponse } from "@/lib/types";

vi.mock("@/lib/api", async (orig) => {
  const mod = await orig<typeof import("@/lib/api")>();
  return { ...mod, api: { ...mod.api, getChatHistory: vi.fn(), sendChat: vi.fn() } };
});

const mocked = vi.mocked(api);

beforeEach(() => {
  mocked.getChatHistory.mockReset().mockResolvedValue([]);
  mocked.sendChat.mockReset();
});

describe("ChatPanel", () => {
  it("renders stored history with inline actions", async () => {
    mocked.getChatHistory.mockResolvedValue([
      { id: "1", role: "user", content: "buy 2 AAPL", actions: null, created_at: "" },
      {
        id: "2",
        role: "assistant",
        content: "Mock: buying 2 AAPL.",
        actions: {
          trades: [{ ticker: "AAPL", side: "buy", quantity: 2, status: "executed", price: 190 }],
          watchlist_changes: [{ ticker: "PYPL", action: "add", status: "applied" }],
        },
        created_at: "",
      },
    ]);
    render(<ChatPanel />);
    const assistant = await screen.findByText("Mock: buying 2 AAPL.");
    expect(assistant.closest("[data-testid=chat-message]")).toHaveAttribute("data-role", "assistant");
    const actions = screen.getAllByTestId("chat-action");
    expect(actions[0]).toHaveTextContent("Bought 2 AAPL at $190.00");
    expect(actions[1]).toHaveTextContent("Added PYPL to watchlist");
  });

  it("shows a loading indicator, then the reply and failed actions", async () => {
    let resolve!: (r: ChatResponse) => void;
    mocked.sendChat.mockReturnValue(new Promise((r) => (resolve = r)));
    const onReply = vi.fn();
    render(<ChatPanel onReply={onReply} />);

    await userEvent.type(screen.getByTestId("chat-input"), "sell 5 TSLA");
    await userEvent.click(screen.getByTestId("chat-send"));
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    const user = screen.getAllByTestId("chat-message").find((m) => m.dataset.role === "user")!;
    expect(user).toHaveTextContent("sell 5 TSLA");
    expect(screen.getByTestId("chat-input")).toHaveValue("");

    const reply: ChatResponse = {
      message: "Mock: selling 5 TSLA.",
      trades: [{ ticker: "TSLA", side: "sell", quantity: 5, status: "failed", error: "Insufficient shares" }],
      watchlist_changes: [],
    };
    resolve(reply);
    const msg = await screen.findByText("Mock: selling 5 TSLA.");
    expect(screen.queryByTestId("chat-loading")).toBeNull();
    const action = within(msg.closest("[data-testid=chat-message]") as HTMLElement).getByTestId("chat-action");
    expect(action).toHaveTextContent("Sell 5 TSLA failed: Insufficient shares");
    expect(action).toHaveAttribute("data-status", "failed");
    expect(onReply).toHaveBeenCalledWith({ trades: reply.trades, watchlist_changes: [] });
  });

  it("reports a failed send inline", async () => {
    mocked.sendChat.mockRejectedValue(new Error("Request failed (500)"));
    render(<ChatPanel />);
    await userEvent.type(screen.getByTestId("chat-input"), "hello{enter}");
    expect(await screen.findByText(/Message not delivered/)).toBeInTheDocument();
  });

  it("collapses and expands", async () => {
    render(<ChatPanel />);
    await userEvent.click(screen.getByLabelText("Collapse assistant"));
    expect(screen.getByTestId("chat-panel")).toHaveAttribute("data-open", "false");
    expect(screen.queryByTestId("chat-input")).toBeNull();
    await userEvent.click(screen.getByLabelText("Open FinAlly assistant"));
    expect(screen.getByTestId("chat-input")).toBeInTheDocument();
  });
});
