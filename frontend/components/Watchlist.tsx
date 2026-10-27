"use client";

import { useState, type FormEvent } from "react";
import { Sparkline } from "@/components/charts/Sparkline";
import { formatPercent, formatPrice, trend } from "@/lib/format";
import type { PricePoint, PriceUpdate, WatchlistEntry } from "@/lib/types";

interface WatchlistProps {
  entries: WatchlistEntry[];
  prices: Record<string, PriceUpdate>;
  history: Record<string, PricePoint[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}

const TONE = { up: "text-up", down: "text-down", flat: "text-muted" } as const;

/** Price that flashes green/red for ~500ms whenever it changes. */
export function FlashingPrice({ ticker, price }: { ticker: string; price: number | null }) {
  const [shown, setShown] = useState(price);
  const [flash, setFlash] = useState<{ dir: "up" | "down"; n: number } | null>(null);

  // Adjust state during render when the price prop changes (no effect round-trip).
  if (price !== shown) {
    if (price != null && shown != null && price !== shown) {
      setFlash({ dir: price > shown ? "up" : "down", n: (flash?.n ?? 0) + 1 });
    }
    setShown(price);
  }

  return (
    <span
      // Remount on each tick so the fade animation restarts even if the direction repeats.
      key={flash?.n ?? 0}
      data-testid={`watchlist-price-${ticker}`}
      onAnimationEnd={() => setFlash(null)}
      className={`num inline-block rounded-sm px-1 text-right text-ink ${flash ? `flash-${flash.dir}` : ""}`}
    >
      {formatPrice(price)}
    </span>
  );
}

export function Watchlist({ entries, prices, history, selected, onSelect, onAdd, onRemove }: WatchlistProps) {
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const ticker = draft.trim().toUpperCase();
    if (!ticker) return;
    setBusy(true);
    setError(null);
    try {
      await onAdd(ticker);
      setDraft("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add ticker");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Watchlist" className="flex min-h-0 flex-col">
      <div className="flex items-baseline justify-between px-3 pb-1.5 pt-2.5">
        <h2 className="text-[13px] font-semibold text-ink">Watchlist</h2>
        <span className="text-[11px] text-faint">vs. session open</span>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {entries.map((entry) => {
          const live = prices[entry.ticker];
          const price = live?.price ?? entry.price;
          const changePct = live?.change_percent_open ?? entry.change_percent_open;
          const isSelected = entry.ticker === selected;
          return (
            <li
              key={entry.ticker}
              data-testid={`watchlist-row-${entry.ticker}`}
              data-selected={isSelected}
              onClick={() => onSelect(entry.ticker)}
              className={`group grid cursor-pointer grid-cols-[3.75rem_1fr_auto_3.75rem_1.25rem] items-center gap-2 border-l-2 py-1.5 pl-2.5 pr-2 hover:bg-raised ${
                isSelected ? "border-accent bg-raised" : "border-transparent"
              }`}
            >
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onSelect(entry.ticker);
                }}
                className={`truncate text-left font-semibold ${isSelected ? "text-accent" : "text-ink"}`}
              >
                {entry.ticker}
              </button>
              <Sparkline points={history[entry.ticker] ?? []} />
              <FlashingPrice ticker={entry.ticker} price={price} />
              <span className={`num text-right text-[12px] ${TONE[trend(changePct)]}`}>
                {formatPercent(changePct)}
              </span>
              <button
                type="button"
                data-testid={`watchlist-remove-${entry.ticker}`}
                aria-label={`Remove ${entry.ticker} from watchlist`}
                title={`Remove ${entry.ticker}`}
                onClick={(e) => {
                  e.stopPropagation();
                  void onRemove(entry.ticker);
                }}
                className="text-faint opacity-0 hover:text-down focus-visible:opacity-100 group-hover:opacity-100"
              >
                ×
              </button>
            </li>
          );
        })}
        {entries.length === 0 && (
          <li className="px-3 py-4 text-muted">Add a ticker below to start watching it.</li>
        )}
      </ul>

      <form onSubmit={submit} className="border-t border-line p-2.5">
        <div className="flex gap-1.5">
          <input
            data-testid="watchlist-add-input"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Ticker, e.g. PYPL"
            aria-label="Ticker to add"
            maxLength={10}
            autoComplete="off"
            spellCheck={false}
            className="num min-w-0 flex-1 rounded-sm border border-line-strong bg-base px-2 py-1 uppercase text-ink placeholder:normal-case placeholder:text-faint focus:border-blue focus:outline-none"
          />
          <button
            type="submit"
            data-testid="watchlist-add-button"
            disabled={busy}
            className="rounded-sm bg-purple px-3 py-1 font-medium text-white hover:bg-purple-hover disabled:opacity-50"
          >
            Add
          </button>
        </div>
        {error && (
          <p role="alert" className="mt-1.5 text-[12px] text-down">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}
