import { formatCurrency, formatPercent, formatSignedCurrency, trend } from "@/lib/format";
import type { ConnectionStatus } from "@/lib/types";

interface HeaderProps {
  totalValue: number | null;
  cashBalance: number | null;
  unrealizedPnl: number | null;
  costBasis: number;
  status: ConnectionStatus;
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  connected: "Live",
  reconnecting: "Reconnecting",
  disconnected: "Offline",
};

const STATUS_COLOR: Record<ConnectionStatus, string> = {
  connected: "bg-up",
  reconnecting: "bg-accent dot-pulse",
  disconnected: "bg-down",
};

const TONE = { up: "text-up", down: "text-down", flat: "text-muted" } as const;

export function Header({ totalValue, cashBalance, unrealizedPnl, costBasis, status }: HeaderProps) {
  const pnlPct = unrealizedPnl != null && costBasis > 0 ? (unrealizedPnl / costBasis) * 100 : null;
  return (
    <header className="flex h-14 shrink-0 items-center gap-8 border-b border-line bg-panel px-4">
      <div className="flex items-baseline gap-2">
        <span className="text-[19px] font-semibold tracking-tight text-ink">
          Fin<span className="text-accent">Ally</span>
        </span>
        <span className="hidden text-faint md:inline">trading workstation</span>
      </div>

      <dl className="flex items-baseline gap-7">
        <div className="flex items-baseline gap-2">
          <dt className="text-muted">Portfolio</dt>
          <dd data-testid="total-value" className="num text-[20px] font-medium text-ink">
            {totalValue == null ? "—" : formatCurrency(totalValue)}
          </dd>
        </div>
        <div className="flex items-baseline gap-2">
          <dt className="text-muted">Cash</dt>
          <dd data-testid="cash-balance" className="num text-[15px] text-ink">
            {cashBalance == null ? "—" : formatCurrency(cashBalance)}
          </dd>
        </div>
        <div className="hidden items-baseline gap-2 lg:flex">
          <dt className="text-muted">Unrealized</dt>
          <dd className={`num text-[15px] ${TONE[trend(unrealizedPnl)]}`}>
            {unrealizedPnl == null ? "—" : formatSignedCurrency(unrealizedPnl)}
            {pnlPct != null && <span className="ml-1.5 text-[12px]">{formatPercent(pnlPct)}</span>}
          </dd>
        </div>
      </dl>

      <div className="ml-auto flex items-center gap-2 text-muted" title={`Price stream: ${STATUS_LABEL[status]}`}>
        <span
          data-testid="connection-status"
          data-status={status}
          role="status"
          aria-label={`Price stream ${STATUS_LABEL[status].toLowerCase()}`}
          className={`inline-block size-2 rounded-full ${STATUS_COLOR[status]}`}
        />
        <span className="text-[12px]">{STATUS_LABEL[status]}</span>
      </div>
    </header>
  );
}
