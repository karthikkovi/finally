const usd = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatCurrency(value: number): string {
  return usd.format(value);
}

/** Price without the currency symbol or grouping, for dense tables. */
export function formatPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toFixed(2);
}

export function formatSignedCurrency(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${usd.format(Math.abs(value))}`;
}

export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}%`;
}

export function formatQuantity(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

/** Sign class for P&L style values. */
export function trend(value: number | null | undefined): "up" | "down" | "flat" {
  if (value == null || Math.abs(value) < 1e-9) return "flat";
  return value > 0 ? "up" : "down";
}
