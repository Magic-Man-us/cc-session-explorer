/** Token accounting mirrored from the cc-session-explorer `TokenBreakdown` payload. */
export interface TokenBreakdown {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  total_tokens: number;
  cache_hit_rate: number | null;
}

/** The four token categories, in stacking order (cache first, output last). */
export type SeriesKey =
  | "cache_read_tokens"
  | "cache_creation_tokens"
  | "input_tokens"
  | "output_tokens";

export const SERIES: readonly SeriesKey[] = [
  "cache_read_tokens",
  "cache_creation_tokens",
  "input_tokens",
  "output_tokens",
];

export const SERIES_LABELS: Record<SeriesKey, string> = {
  input_tokens: "input",
  output_tokens: "output",
  cache_read_tokens: "cache read",
  cache_creation_tokens: "cache write",
};

/** Token-category colors, resolved from the design tokens. */
export const SERIES_COLORS: Record<SeriesKey, string> = {
  input_tokens: "var(--blue)",
  output_tokens: "var(--red)",
  cache_read_tokens: "var(--green)",
  cache_creation_tokens: "var(--amber)",
};

/** Semantic accent names available as design tokens. */
export type Accent = "blue" | "red" | "green" | "amber" | "violet";

export const accentVar = (accent: Accent): string => `var(--${accent})`;
