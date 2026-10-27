"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { ChatPanel } from "@/components/ChatPanel";
import { TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import { Header } from "@/components/Header";
import { Heatmap } from "@/components/Heatmap";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeBar } from "@/components/TradeBar";
import { Watchlist } from "@/components/Watchlist";
import { usePriceStream } from "@/hooks/usePriceStream";
import { api } from "@/lib/api";
import { formatCurrency, formatPercent, formatPrice, formatSignedCurrency, trend } from "@/lib/format";
import { revaluePortfolio, snapshotsToPoints } from "@/lib/portfolio";
import type { Portfolio, Snapshot, WatchlistEntry } from "@/lib/types";

const STARTING_CASH = 10_000;
const TONE = { up: "text-up", down: "text-down", flat: "text-muted" } as const;

function Panel({ title, aside, children, className = "" }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`flex min-h-0 min-w-0 flex-col bg-panel ${className}`}>
      <div className="flex items-baseline justify-between px-3 pb-1 pt-2">
        <h2 className="text-[13px] font-semibold text-ink">{title}</h2>
        {aside && <div className="text-[11.5px] text-muted">{aside}</div>}
      </div>
      <div className="relative min-h-0 flex-1">{children}</div>
    </section>
  );
}

export function Workstation() {
  const stream = usePriceStream();
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [tradeTicker, setTradeTicker] = useState<string | null>(null);

  const refreshWatchlist = useCallback(() => api.getWatchlist().then(setEntries).catch(() => {}), []);
  const refreshPortfolio = useCallback(() => api.getPortfolio().then(setPortfolio).catch(() => {}), []);
  const refreshHistory = useCallback(() => api.getHistory().then(setSnapshots).catch(() => {}), []);

  useEffect(() => {
    void refreshWatchlist();
    void refreshPortfolio();
    void refreshHistory();
    // Snapshots are recorded every 30s server-side; the portfolio may also change from elsewhere.
    const history = setInterval(refreshHistory, 15_000);
    const book = setInterval(refreshPortfolio, 10_000);
    return () => {
      clearInterval(history);
      clearInterval(book);
    };
  }, [refreshWatchlist, refreshPortfolio, refreshHistory]);

  const live = useMemo(() => (portfolio ? revaluePortfolio(portfolio, stream.prices) : null), [portfolio, stream.prices]);

  const active = selected ?? entries[0]?.ticker ?? null;
  const tradeValue = tradeTicker ?? active ?? "";
  const activeQuote = active ? stream.prices[active] : undefined;
  const activeEntry = entries.find((e) => e.ticker === active);
  const activePrice = activeQuote?.price ?? activeEntry?.price ?? null;
  const activeChange = activeQuote?.change_percent_open ?? activeEntry?.change_percent_open ?? null;

  const select = useCallback((ticker: string) => {
    setSelected(ticker);
    setTradeTicker(ticker);
  }, []);

  const pnlPoints = useMemo(() => {
    const points = snapshotsToPoints(snapshots);
    // Extend the recorded history with the live value so the line moves with the market.
    const now = Math.floor(Math.max(0, ...Object.values(stream.prices).map((p) => p.timestamp)));
    const last = points[points.length - 1];
    if (live && points.length && (!last || now > last.time)) points.push({ time: now, value: live.total_value });
    return points;
  }, [snapshots, live, stream.prices]);

  const sessionChange = live ? live.total_value - STARTING_CASH : null;

  return (
    <div className="flex h-screen min-h-[640px] flex-col overflow-hidden">
      <Header
        totalValue={live?.total_value ?? null}
        cashBalance={live?.cash_balance ?? null}
        unrealizedPnl={live?.unrealized_pnl ?? null}
        costBasis={live?.cost_basis ?? 0}
        status={stream.status}
      />

      <div className="flex min-h-0 flex-1">
        <aside className="flex w-[330px] shrink-0 flex-col border-r border-line bg-panel">
          <Watchlist
            entries={entries}
            prices={stream.prices}
            history={stream.history}
            selected={active}
            onSelect={select}
            onAdd={async (ticker) => {
              await api.addTicker(ticker);
              await refreshWatchlist();
            }}
            onRemove={async (ticker) => {
              setEntries((list) => list.filter((e) => e.ticker !== ticker));
              try {
                await api.removeTicker(ticker);
              } finally {
                await refreshWatchlist();
              }
            }}
          />
        </aside>

        <main className="grid min-h-0 min-w-0 flex-1 grid-rows-[minmax(240px,1.15fr)_auto_minmax(200px,0.85fr)_minmax(150px,0.75fr)] gap-px bg-line">
          <section
            data-testid="main-chart"
            data-ticker={active ?? ""}
            aria-label={`${active ?? "No ticker"} price chart`}
            className="flex min-h-0 flex-col bg-panel"
          >
            <div className="flex items-baseline gap-4 px-4 pb-1 pt-3">
              <span className="text-[26px] font-semibold leading-none tracking-tight text-accent">{active ?? "—"}</span>
              <span className="num text-[22px] leading-none text-ink">{formatPrice(activePrice)}</span>
              <span className={`num text-[14px] ${TONE[trend(activeChange)]}`}>{formatPercent(activeChange)}</span>
              <span className="ml-auto text-[11.5px] text-muted">Since page load, 1s resolution</span>
            </div>
            <div className="relative min-h-0 flex-1">
              {active && <TimeSeriesChart key={active} data={stream.history[active] ?? []} color="#209dd7" />}
              {active && (stream.history[active]?.length ?? 0) < 2 && (
                <p className="pointer-events-none absolute inset-0 grid place-items-center text-muted">
                  Collecting prices for {active}…
                </p>
              )}
            </div>
          </section>

          <TradeBar
            ticker={tradeValue}
            onTickerChange={setTradeTicker}
            price={stream.prices[tradeValue.trim().toUpperCase()]?.price ?? null}
            onTrade={async (ticker, quantity, side) => {
              const { trade, portfolio: next } = await api.trade(ticker, quantity, side);
              setPortfolio(next);
              void refreshHistory();
              void refreshWatchlist();
              return trade;
            }}
          />

          <div className="grid min-h-0 grid-cols-2 gap-px">
            <Panel title="Holdings heatmap" aside="Sized by weight, colored by P&L">
              <div className="absolute inset-x-3 bottom-3 top-1">
                <Heatmap positions={live?.positions ?? []} onSelect={select} />
              </div>
            </Panel>
            <Panel
              title="Portfolio value"
              aside={
                sessionChange != null && (
                  <span className={`num ${TONE[trend(sessionChange)]}`}>
                    {formatSignedCurrency(sessionChange)} vs. {formatCurrency(STARTING_CASH)} start
                  </span>
                )
              }
            >
              <div data-testid="pnl-chart" data-points={snapshots.length} className="absolute inset-0">
                {pnlPoints.length > 1 ? (
                  <TimeSeriesChart
                    kind="baseline"
                    baseValue={STARTING_CASH}
                    data={pnlPoints}
                    formatValue={(v) => formatCurrency(v)}
                  />
                ) : (
                  <p className="grid h-full place-items-center px-4 text-center text-muted">
                    Portfolio value is recorded every 30 seconds and after each trade.
                  </p>
                )}
              </div>
            </Panel>
          </div>

          <Panel title="Positions" aside={live ? `${live.positions.length} open` : undefined}>
            <div className="absolute inset-0 overflow-auto">
              <PositionsTable positions={live?.positions ?? []} onSelect={select} />
            </div>
          </Panel>
        </main>

        <ChatPanel
          onReply={(actions) => {
            void refreshPortfolio();
            void refreshHistory();
            if (actions.watchlist_changes.length || actions.trades.length) void refreshWatchlist();
          }}
        />
      </div>
    </div>
  );
}
