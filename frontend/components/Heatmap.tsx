"use client";

import { useElementSize } from "@/hooks/useElementSize";
import { formatCurrency, formatPercent, formatSignedCurrency } from "@/lib/format";
import { pnlSign } from "@/lib/portfolio";
import { pnlColor, squarify } from "@/lib/treemap";
import type { Position } from "@/lib/types";

interface HeatmapProps {
  positions: Position[];
  onSelect?: (ticker: string) => void;
  /** Fixed layout size; otherwise the container is measured. */
  size?: { width: number; height: number };
}

const GAP = 2;

export function Heatmap({ positions, onSelect, size }: HeatmapProps) {
  const [ref, measured] = useElementSize<HTMLDivElement>();
  const { width, height } = size ?? measured;
  const rects = squarify(
    positions.map((p) => ({ value: p.market_value, item: p })),
    width,
    height,
  );

  return (
    <div data-testid="heatmap" ref={ref} className="relative h-full w-full overflow-hidden">
      {positions.length === 0 && (
        <p className="absolute inset-0 grid place-items-center px-4 text-center text-muted">
          No positions yet. Buy a ticker to see it sized by weight here.
        </p>
      )}
      {rects.map(({ item: p, x, y, w, h }) => {
        const roomy = w > 58 && h > 34;
        return (
          <button
            type="button"
            key={p.ticker}
            data-testid={`heatmap-cell-${p.ticker}`}
            data-pnl={pnlSign(p.unrealized_pnl)}
            onClick={() => onSelect?.(p.ticker)}
            title={`${p.ticker}: ${formatCurrency(p.market_value)}, ${formatSignedCurrency(p.unrealized_pnl)} (${formatPercent(p.unrealized_pnl_percent)})`}
            className="absolute flex flex-col items-start justify-start overflow-hidden rounded-[3px] p-1.5 text-left transition-[left,top,width,height] duration-300 hover:brightness-110"
            style={{
              left: x,
              top: y,
              width: Math.max(w - GAP, 1),
              height: Math.max(h - GAP, 1),
              backgroundColor: pnlColor(p.unrealized_pnl_percent),
            }}
          >
            {w > 30 && h > 16 && <span className="text-[12px] font-semibold leading-none text-white">{p.ticker}</span>}
            {roomy && (
              <span className="num mt-1 text-[11px] leading-none text-white/85">
                {formatPercent(p.unrealized_pnl_percent)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
