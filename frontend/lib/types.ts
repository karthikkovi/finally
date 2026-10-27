export type Direction = "up" | "down" | "flat";

export interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  timestamp: number; // unix seconds
  change: number;
  change_percent: number;
  direction: Direction;
  open_price: number;
  change_percent_open: number;
}

export interface WatchlistEntry {
  ticker: string;
  price: number | null;
  previous_price: number | null;
  change: number | null;
  change_percent: number | null;
  direction: Direction | null;
  open_price: number | null;
  change_percent_open: number | null;
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_percent: number;
}

export interface Portfolio {
  cash_balance: number;
  total_value: number;
  positions_value: number;
  unrealized_pnl: number;
  positions: Position[];
}

export interface Trade {
  id: string;
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  executed_at: string;
}

export interface Snapshot {
  total_value: number;
  recorded_at: string;
}

export interface ChatTradeAction {
  ticker: string;
  side: "buy" | "sell";
  quantity: number;
  status: "executed" | "failed";
  price?: number;
  error?: string;
}

export interface ChatWatchlistAction {
  ticker: string;
  action: "add" | "remove";
  status: "applied" | "failed";
  error?: string;
}

export interface ChatResponse {
  message: string;
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
}

export interface ChatActions {
  trades: ChatTradeAction[];
  watchlist_changes: ChatWatchlistAction[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  actions: ChatActions | null;
  created_at: string;
  /** Client-only marker for messages that failed to send. */
  error?: boolean;
}

export type ConnectionStatus = "connected" | "reconnecting" | "disconnected";

export interface PricePoint {
  time: number; // unix seconds
  value: number;
}
