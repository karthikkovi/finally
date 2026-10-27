import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { planUpdate, TimeSeriesChart } from "@/components/charts/TimeSeriesChart";
import type { UTCTimestamp } from "lightweight-charts";

const series = { setData: vi.fn(), update: vi.fn(), applyOptions: vi.fn() };
const timeScale = { fitContent: vi.fn() };
const chart = { addSeries: vi.fn(() => series), timeScale: () => timeScale, remove: vi.fn() };

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn(() => chart),
  AreaSeries: "Area",
  BaselineSeries: "Baseline",
  ColorType: { Solid: "solid" },
  LineStyle: { Dotted: 1, Dashed: 2 },
}));

const pts = (...times: number[]) => times.map((t) => ({ time: t, value: t * 10 }));

beforeEach(() => {
  for (const fn of [series.setData, series.update, timeScale.fitContent]) fn.mockClear();
});

describe("planUpdate", () => {
  const cp = (...times: number[]) => times.map((t) => ({ time: t as UTCTimestamp, value: t }));

  it("resets on first draw and when data no longer reaches the last drawn time", () => {
    expect(planUpdate(null, cp(1, 2)).mode).toBe("reset");
    expect(planUpdate(5, cp(1, 2)).mode).toBe("reset");
    expect(planUpdate(5, []).mode).toBe("reset");
  });

  it("appends the replaced last point and anything newer", () => {
    expect(planUpdate(2, cp(1, 2, 3, 4))).toEqual({ mode: "append", points: cp(2, 3, 4) });
  });
});

describe("TimeSeriesChart", () => {
  it("fits once on first load, then appends without refitting", () => {
    const { rerender } = render(<TimeSeriesChart data={pts(1, 2)} />);
    expect(series.setData).toHaveBeenCalledTimes(1);
    expect(timeScale.fitContent).toHaveBeenCalledTimes(1);

    rerender(<TimeSeriesChart data={pts(1, 2, 3)} />);
    rerender(<TimeSeriesChart data={pts(1, 2, 3, 4)} />);
    expect(series.setData).toHaveBeenCalledTimes(1);
    expect(series.update).toHaveBeenLastCalledWith({ time: 4, value: 40 });
    expect(timeScale.fitContent).toHaveBeenCalledTimes(1);
  });

  it("waits for two points before fitting", () => {
    const { rerender } = render(<TimeSeriesChart data={pts(1)} />);
    expect(timeScale.fitContent).not.toHaveBeenCalled();
    rerender(<TimeSeriesChart data={pts(1, 2)} />);
    expect(timeScale.fitContent).toHaveBeenCalledTimes(1);
  });

  it("refits after remounting, e.g. for a newly selected ticker", () => {
    const { rerender } = render(<TimeSeriesChart key="AAPL" data={pts(1, 2)} />);
    rerender(<TimeSeriesChart key="MSFT" data={pts(5, 6)} />);
    expect(timeScale.fitContent).toHaveBeenCalledTimes(2);
  });
});
