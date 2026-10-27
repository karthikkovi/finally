import { formatCurrency, formatPercent, formatPrice, formatQuantity, formatSignedCurrency, trend } from "@/lib/format";
import type { Position } from "@/lib/types";

interface PositionsTableProps {
  positions: Position[];
  onSelect?: (ticker: string) => void;
}

const TONE = { up: "text-up", down: "text-down", flat: "text-muted" } as const;

export function PositionsTable({ positions, onSelect }: PositionsTableProps) {
  const sorted = [...positions].sort((a, b) => b.market_value - a.market_value);
  return (
    <table data-testid="positions-table" className="w-full border-collapse text-[12.5px]">
      <thead className="sticky top-0 bg-panel text-left text-muted">
        <tr className="border-b border-line">
          <th className="py-1.5 pl-3 pr-2 font-medium">Ticker</th>
          <th className="px-2 text-right font-medium">Qty</th>
          <th className="px-2 text-right font-medium">Avg cost</th>
          <th className="px-2 text-right font-medium">Price</th>
          <th className="px-2 text-right font-medium">Value</th>
          <th className="px-2 text-right font-medium">Unrealized P&amp;L</th>
          <th className="pl-2 pr-3 text-right font-medium">Change</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((p) => {
          const tone = TONE[trend(p.unrealized_pnl)];
          return (
            <tr
              key={p.ticker}
              data-testid={`position-row-${p.ticker}`}
              onClick={() => onSelect?.(p.ticker)}
              className="cursor-pointer border-b border-line/60 hover:bg-raised"
            >
              <td className="py-1.5 pl-3 pr-2 font-semibold text-ink">{p.ticker}</td>
              <td className="num px-2 text-right">{formatQuantity(p.quantity)}</td>
              <td className="num px-2 text-right text-muted">{formatPrice(p.avg_cost)}</td>
              <td className="num px-2 text-right">{formatPrice(p.current_price)}</td>
              <td className="num px-2 text-right">{formatCurrency(p.market_value)}</td>
              <td className={`num px-2 text-right ${tone}`}>{formatSignedCurrency(p.unrealized_pnl)}</td>
              <td className={`num pl-2 pr-3 text-right ${tone}`}>{formatPercent(p.unrealized_pnl_percent)}</td>
            </tr>
          );
        })}
        {sorted.length === 0 && (
          <tr>
            <td colSpan={7} className="px-3 py-4 text-muted">
              No open positions. Use the trade bar or ask FinAlly to place an order.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
