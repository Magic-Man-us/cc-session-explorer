import { fmtTok } from "../format";

export interface StatBarRow {
  label: string;
  value: number;
  /** Bar color — a token var like `var(--blue)` or any CSS color. */
  color: string;
}

export interface StatBarProps {
  rows: ReadonlyArray<StatBarRow>;
  /** Format the numeric value. Defaults to the dashboard's compact token format. */
  format?: (value: number) => string;
  /** Fix the 100% reference. Defaults to the largest row value. */
  max?: number;
}

/** Horizontal labelled progress bars, one per row, scaled to a shared max. */
export function StatBar({ rows, format = fmtTok, max }: StatBarProps) {
  const reference = Math.max(1, max ?? Math.max(0, ...rows.map((row) => row.value)));
  return (
    <div className="ju-buckets">
      {rows.map((row) => (
        <div className="ju-bucket" key={row.label}>
          <div className="ju-bucket-name">{row.label}</div>
          <div className="ju-track">
            <div
              className="ju-fill"
              style={{ background: row.color, width: `${(100 * (row.value || 0)) / reference}%` }}
            />
          </div>
          <div className="ju-num">{format(row.value)}</div>
        </div>
      ))}
    </div>
  );
}
