export interface TreemapInput<T> {
  value: number;
  item: T;
}

export interface TreemapRect<T> {
  item: T;
  value: number;
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Squarified treemap (Bruls et al.) laid out in a width×height box.
 * Items with non-positive values are dropped.
 */
export function squarify<T>(
  inputs: TreemapInput<T>[],
  width: number,
  height: number,
): TreemapRect<T>[] {
  const items = inputs.filter((i) => i.value > 0).sort((a, b) => b.value - a.value);
  const total = items.reduce((s, i) => s + i.value, 0);
  if (!items.length || width <= 0 || height <= 0 || total <= 0) return [];

  const scale = (width * height) / total;
  const areas = items.map((i) => ({ ...i, area: i.value * scale }));
  const out: TreemapRect<T>[] = [];
  let x = 0;
  let y = 0;
  let w = width;
  let h = height;

  const worst = (row: number[], side: number) => {
    const sum = row.reduce((s, a) => s + a, 0);
    const max = Math.max(...row);
    const min = Math.min(...row);
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  };

  let i = 0;
  while (i < areas.length) {
    const side = Math.min(w, h);
    const row = [areas[i].area];
    let j = i + 1;
    while (j < areas.length && worst([...row, areas[j].area], side) <= worst(row, side)) {
      row.push(areas[j].area);
      j++;
    }
    const sum = row.reduce((s, a) => s + a, 0);
    if (w >= h) {
      // lay the row out as a column on the left
      const colW = sum / h;
      let cy = y;
      for (let k = i; k < j; k++) {
        const rh = areas[k].area / colW;
        out.push({ item: areas[k].item, value: areas[k].value, x, y: cy, w: colW, h: rh });
        cy += rh;
      }
      x += colW;
      w -= colW;
    } else {
      const rowH = sum / w;
      let cx = x;
      for (let k = i; k < j; k++) {
        const rw = areas[k].area / rowH;
        out.push({ item: areas[k].item, value: areas[k].value, x: cx, y, w: rw, h: rowH });
        cx += rw;
      }
      y += rowH;
      h -= rowH;
    }
    i = j;
  }
  return out;
}

const NEUTRAL = [42, 50, 64]; // #2a3240
const UP = [46, 189, 133]; // #2ebd85
const DOWN = [240, 90, 95]; // #f05a5f

/** Diverging fill for a P&L percentage: gray at zero, saturating at ±cap%. */
export function pnlColor(pct: number, cap = 5): string {
  const t = Math.min(Math.abs(pct) / cap, 1);
  const pole = pct >= 0 ? UP : DOWN;
  // keep a floor so even tiny moves are legible as a direction
  const k = Math.abs(pct) < 1e-9 ? 0 : 0.3 + 0.7 * t;
  const mix = NEUTRAL.map((c, idx) => Math.round(c + (pole[idx] - c) * k));
  return `rgb(${mix[0]}, ${mix[1]}, ${mix[2]})`;
}
