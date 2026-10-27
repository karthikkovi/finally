import type {
  ChatActions,
  ChatMessage,
  ChatResponse,
  Portfolio,
  Snapshot,
  Trade,
  WatchlistEntry,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(detail, res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/** The backend stores chat actions as JSON; accept either the object form or a bare list. */
export function normalizeActions(raw: unknown): ChatActions | null {
  if (!raw) return null;
  if (Array.isArray(raw)) {
    return {
      trades: raw.filter((a) => a && "side" in a),
      watchlist_changes: raw.filter((a) => a && "action" in a),
    };
  }
  if (typeof raw === "object") {
    const obj = raw as Partial<ChatActions>;
    return { trades: obj.trades ?? [], watchlist_changes: obj.watchlist_changes ?? [] };
  }
  return null;
}

export const api = {
  getPortfolio: () => request<Portfolio>("/api/portfolio"),
  getHistory: () =>
    request<{ snapshots: Snapshot[] }>("/api/portfolio/history").then((r) => r.snapshots),
  trade: (ticker: string, quantity: number, side: "buy" | "sell") =>
    request<{ trade: Trade; portfolio: Portfolio }>("/api/portfolio/trade", {
      method: "POST",
      body: JSON.stringify({ ticker, quantity, side }),
    }),
  getWatchlist: () =>
    request<{ tickers: WatchlistEntry[] }>("/api/watchlist").then((r) => r.tickers),
  addTicker: (ticker: string) =>
    request<{ ticker: string }>("/api/watchlist", {
      method: "POST",
      body: JSON.stringify({ ticker }),
    }),
  removeTicker: (ticker: string) =>
    request<void>(`/api/watchlist/${encodeURIComponent(ticker)}`, { method: "DELETE" }),
  sendChat: (message: string) =>
    request<ChatResponse>("/api/chat", { method: "POST", body: JSON.stringify({ message }) }),
  getChatHistory: () =>
    request<{ messages: ChatMessage[] }>("/api/chat/history").then((r) =>
      r.messages.map((m) => ({ ...m, actions: normalizeActions(m.actions) })),
    ),
};
