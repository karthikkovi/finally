"use client";

import { useEffect, useRef } from "react";
import {
  AreaSeries,
  BaselineSeries,
  ColorType,
  createChart,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import type { PricePoint } from "@/lib/types";

export interface TimeSeriesChartProps {
  data: PricePoint[];
  /** "area" for a single price series; "baseline" splits above/below `baseValue` (gain vs loss). */
  kind?: "area" | "baseline";
  color?: string;
  baseValue?: number;
  formatValue?: (value: number) => string;
}

const UP = "#2ebd85";
const DOWN = "#f05a5f";

/** Collapse to one point per whole second; the chart needs strictly increasing integer-ish times. */
export function toChartData(points: PricePoint[]) {
  const out: { time: UTCTimestamp; value: number }[] = [];
  for (const p of points) {
    const time = Math.floor(p.time) as UTCTimestamp;
    const last = out[out.length - 1];
    if (last && last.time === time) last.value = p.value;
    else if (!last || time > last.time) out.push({ time, value: p.value });
  }
  return out;
}

type ChartPoint = ReturnType<typeof toChartData>[number];

/**
 * Decide how to bring the series up to date with `points`, given the time of the last point
 * already drawn: append (via `series.update`) when the data only grew at the end, otherwise reset.
 */
export function planUpdate(
  lastTime: number | null,
  points: ChartPoint[],
): { mode: "reset"; points: ChartPoint[] } | { mode: "append"; points: ChartPoint[] } {
  const last = points[points.length - 1];
  if (lastTime == null || !last || last.time < lastTime) return { mode: "reset", points };
  return { mode: "append", points: points.filter((p) => p.time >= lastTime) };
}

export function TimeSeriesChart({
  data,
  kind = "area",
  color = "#209dd7",
  baseValue = 0,
  formatValue,
}: TimeSeriesChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | ISeriesApi<"Baseline"> | null>(null);
  /** Time of the last point drawn, and whether the initial fit has happened, for this mount. */
  const drawn = useRef<{ lastTime: number | null; count: number; fitted: boolean }>({
    lastTime: null,
    count: 0,
    fitted: false,
  });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8a95a5",
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: "rgba(47, 58, 73, 0.45)", style: LineStyle.Dotted },
      },
      rightPriceScale: { borderColor: "#212a36", scaleMargins: { top: 0.12, bottom: 0.08 } },
      timeScale: {
        borderColor: "#212a36",
        timeVisible: true,
        secondsVisible: true,
        // New points scroll the view only while the latest point is in view; a user who has
        // panned back in time keeps their range.
        shiftVisibleRangeOnNewBar: true,
        // Keep the first fit from stretching a handful of points across the whole width.
        maxBarSpacing: 12,
      },
      crosshair: {
        vertLine: { color: "#5c6676", labelBackgroundColor: "#2f3a49" },
        horzLine: { color: "#5c6676", labelBackgroundColor: "#2f3a49" },
      },
      localization: formatValue ? { priceFormatter: formatValue } : undefined,
      handleScale: { axisPressedMouseMove: false },
    });
    chartRef.current = chart;
    drawn.current = { lastTime: null, count: 0, fitted: false };
    seriesRef.current =
      kind === "baseline"
        ? chart.addSeries(BaselineSeries, {
            baseValue: { type: "price", price: baseValue },
            topLineColor: UP,
            topFillColor1: "rgba(46, 189, 133, 0.28)",
            topFillColor2: "rgba(46, 189, 133, 0.02)",
            bottomLineColor: DOWN,
            bottomFillColor1: "rgba(240, 90, 95, 0.02)",
            bottomFillColor2: "rgba(240, 90, 95, 0.28)",
            lineWidth: 2,
            priceLineVisible: false,
          })
        : chart.addSeries(AreaSeries, {
            lineColor: color,
            topColor: `${color}55`,
            bottomColor: `${color}05`,
            lineWidth: 2,
            priceLineColor: color,
            priceLineStyle: LineStyle.Dashed,
          });
    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // Series style is fixed per mount; data updates go through the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [kind]);

  useEffect(() => {
    if (kind === "baseline") {
      (seriesRef.current as ISeriesApi<"Baseline"> | null)?.applyOptions({
        baseValue: { type: "price", price: baseValue },
      });
    }
  }, [kind, baseValue]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const state = drawn.current;
    const plan = planUpdate(state.lastTime, toChartData(data));
    if (plan.mode === "append") {
      for (const p of plan.points) series.update(p);
      state.count += plan.points.filter((p) => p.time > (state.lastTime ?? -Infinity)).length;
    } else {
      series.setData(plan.points);
      state.count = plan.points.length;
    }
    state.lastTime = plan.points[plan.points.length - 1]?.time ?? state.lastTime;
    // Fit once per mount (i.e. per ticker); afterwards the user's zoom and pan are left alone.
    if (!state.fitted && state.count > 1) {
      chartRef.current?.timeScale().fitContent();
      state.fitted = true;
    }
  }, [data]);

  return <div ref={containerRef} className="absolute inset-0" />;
}
