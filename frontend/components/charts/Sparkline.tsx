import type { PricePoint } from "@/lib/types";

interface SparklineProps {
  points: PricePoint[];
  width?: number;
  height?: number;
}

/** Build the SVG path for a series scaled into a width×height box. Exported for tests. */
export function sparklinePath(points: PricePoint[], width: number, height: number): string {
  if (points.length < 2) return "";
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const pad = 1.5;
  return values
    .map((v, i) => {
      const x = i * step;
      const y = pad + (height - 2 * pad) * (1 - (v - min) / span);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join("");
}

/** Price since page load; stroke takes the color of the net move over the window. */
export function Sparkline({ points, width = 84, height = 24 }: SparklineProps) {
  const recent = points.slice(-240);
  const d = sparklinePath(recent, width, height);
  const first = recent[0]?.value ?? 0;
  const last = recent[recent.length - 1]?.value ?? 0;
  const stroke = last > first ? "var(--color-up)" : last < first ? "var(--color-down)" : "var(--color-faint)";
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden="true" className="block">
      {d ? (
        <path d={d} fill="none" stroke={stroke} strokeWidth={1.25} strokeLinejoin="round" />
      ) : (
        <line
          x1={0}
          x2={width}
          y1={height / 2}
          y2={height / 2}
          stroke="var(--color-line-strong)"
          strokeDasharray="2 3"
        />
      )}
    </svg>
  );
}
