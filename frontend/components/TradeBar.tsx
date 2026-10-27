"use client";

import { useState } from "react";
import { formatCurrency, formatQuantity } from "@/lib/format";
import type { Trade } from "@/lib/types";

interface TradeBarProps {
  ticker: string;
  onTickerChange: (ticker: string) => void;
  /** Current price of the ticker in the field, for the estimated cost hint. */
  price: number | null;
  onTrade: (ticker: string, quantity: number, side: "buy" | "sell") => Promise<Trade>;
}

export function TradeBar({ ticker, onTickerChange, price, onTrade }: TradeBarProps) {
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [filled, setFilled] = useState<Trade | null>(null);
  const [pending, setPending] = useState<"buy" | "sell" | null>(null);

  const qty = Number(quantity);
  const estimate = price != null && qty > 0 ? price * qty : null;

  async function submit(side: "buy" | "sell") {
    const symbol = ticker.trim().toUpperCase();
    setError(null);
    setFilled(null);
    if (!symbol) return setError("Enter a ticker symbol.");
    if (!quantity.trim() || !Number.isFinite(qty) || qty <= 0) {
      return setError("Enter a quantity greater than zero.");
    }
    setPending(side);
    try {
      setFilled(await onTrade(symbol, qty, side));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Trade failed");
    } finally {
      setPending(null);
    }
  }

  return (
    <form
      aria-label="Trade"
      onSubmit={(e) => {
        e.preventDefault();
        void submit("buy");
      }}
      className="flex flex-wrap items-center gap-2 border-t border-line bg-panel px-3 py-2"
    >
      <label className="flex items-center gap-1.5 text-muted">
        Ticker
        <input
          data-testid="trade-ticker"
          value={ticker}
          onChange={(e) => onTickerChange(e.target.value.toUpperCase())}
          maxLength={10}
          autoComplete="off"
          spellCheck={false}
          className="num w-24 rounded-sm border border-line-strong bg-base px-2 py-1 uppercase text-ink focus:border-blue focus:outline-none"
        />
      </label>
      <label className="flex items-center gap-1.5 text-muted">
        Shares
        <input
          data-testid="trade-quantity"
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          inputMode="decimal"
          placeholder="0"
          autoComplete="off"
          className="num w-24 rounded-sm border border-line-strong bg-base px-2 py-1 text-right text-ink placeholder:text-faint focus:border-blue focus:outline-none"
        />
      </label>
      <button
        type="button"
        data-testid="trade-buy"
        disabled={pending != null}
        onClick={() => submit("buy")}
        className="rounded-sm bg-up/15 px-4 py-1 font-semibold text-up ring-1 ring-up/40 hover:bg-up/25 disabled:opacity-50"
      >
        {pending === "buy" ? "Buying…" : "Buy"}
      </button>
      <button
        type="button"
        data-testid="trade-sell"
        disabled={pending != null}
        onClick={() => submit("sell")}
        className="rounded-sm bg-down/15 px-4 py-1 font-semibold text-down ring-1 ring-down/40 hover:bg-down/25 disabled:opacity-50"
      >
        {pending === "sell" ? "Selling…" : "Sell"}
      </button>

      <div className="ml-2 min-w-0 flex-1 truncate text-[12px]" aria-live="polite">
        {error ? (
          <span data-testid="trade-error" role="alert" className="text-down">
            {error}
          </span>
        ) : filled ? (
          <span className="text-ink">
            {filled.side === "buy" ? "Bought" : "Sold"} {formatQuantity(filled.quantity)} {filled.ticker} at{" "}
            <span className="num">{formatCurrency(filled.price)}</span>
          </span>
        ) : estimate != null ? (
          <span className="text-muted">
            Market order, est. <span className="num">{formatCurrency(estimate)}</span>
          </span>
        ) : (
          <span className="text-faint">Market orders fill instantly at the last price.</span>
        )}
      </div>
    </form>
  );
}
