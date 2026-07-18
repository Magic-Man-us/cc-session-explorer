/** Format helpers ported verbatim from the dashboard so labels match exactly. */

export const fmtInt = (n: number | null | undefined): string =>
  Math.round(n ?? 0).toLocaleString();

export const fmtTok = (n: number | null | undefined): string => {
  const v = n ?? 0;
  if (v >= 1_000_000_000) return (v / 1_000_000_000).toFixed(1) + "B";
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + "M";
  if (v >= 1_000) return (v / 1_000).toFixed(1) + "K";
  return String(v);
};

export const money = (n: number | null | undefined): string =>
  "$" + (n ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 });
