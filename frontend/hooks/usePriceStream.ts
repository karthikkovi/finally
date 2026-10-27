"use client";

import { useEffect, useRef, useState } from "react";
import type { ConnectionStatus, PricePoint, PriceUpdate } from "@/lib/types";

/** ~10 minutes of history at the 500ms cadence. */
export const MAX_POINTS = 1200;

export interface PriceStreamState {
  prices: Record<string, PriceUpdate>;
  history: Record<string, PricePoint[]>;
  status: ConnectionStatus;
}

/** Merge one SSE payload into the accumulated price/history state. */
export function applyPriceEvent(
  state: Pick<PriceStreamState, "prices" | "history">,
  payload: Record<string, PriceUpdate>,
  maxPoints = MAX_POINTS,
): Pick<PriceStreamState, "prices" | "history"> {
  const prices = { ...state.prices };
  const history = { ...state.history };
  for (const [ticker, update] of Object.entries(payload)) {
    if (!update || typeof update.price !== "number") continue;
    const prev = prices[ticker];
    prices[ticker] = update;
    const series = history[ticker] ?? [];
    const last = series[series.length - 1];
    if (prev && prev.timestamp === update.timestamp && last) continue;
    // lightweight-charts needs strictly increasing times
    if (last && update.timestamp <= last.time) continue;
    const next = [...series, { time: update.timestamp, value: update.price }];
    history[ticker] = next.length > maxPoints ? next.slice(next.length - maxPoints) : next;
  }
  return { prices, history };
}

export function usePriceStream(url = "/api/stream/prices"): PriceStreamState {
  const [state, setState] = useState<PriceStreamState>({
    prices: {},
    history: {},
    status: "reconnecting",
  });
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let closed = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      const es = new EventSource(url);
      sourceRef.current = es;
      es.onopen = () => setState((s) => ({ ...s, status: "connected" }));
      es.onmessage = (ev) => {
        let payload: Record<string, PriceUpdate>;
        try {
          payload = JSON.parse(ev.data);
        } catch {
          return;
        }
        setState((s) => ({ ...s, ...applyPriceEvent(s, payload), status: "connected" }));
      };
      es.onerror = () => {
        if (closed) return;
        if (es.readyState === EventSource.CLOSED) {
          // The browser gave up (e.g. non-200 response); retry ourselves.
          setState((s) => ({ ...s, status: "disconnected" }));
          es.close();
          retryTimer = setTimeout(connect, 3000);
        } else {
          // EventSource is retrying on its own.
          setState((s) => ({ ...s, status: "reconnecting" }));
        }
      };
    };

    // An open stream doesn't always error when the network drops, so follow the browser's
    // online/offline signal too: drop the stream while offline and reconnect when back.
    const goOffline = () => {
      clearTimeout(retryTimer);
      sourceRef.current?.close();
      setState((s) => ({ ...s, status: "disconnected" }));
    };
    const goOnline = () => {
      clearTimeout(retryTimer);
      sourceRef.current?.close();
      setState((s) => ({ ...s, status: "reconnecting" }));
      connect();
    };
    window.addEventListener("offline", goOffline);
    window.addEventListener("online", goOnline);

    connect();
    return () => {
      closed = true;
      clearTimeout(retryTimer);
      window.removeEventListener("offline", goOffline);
      window.removeEventListener("online", goOnline);
      sourceRef.current?.close();
    };
  }, [url]);

  return state;
}
