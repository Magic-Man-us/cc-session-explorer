export interface BarSeries {
  key: string;
  label: string;
  /** Segment color — a token var like `var(--blue)` or any CSS color. */
  color: string;
}

export interface BarDatum {
  /** Stable id for the bar, used as the React key and hover payload. */
  id: string;
  /** Value per series key; missing keys count as zero. */
  values: Record<string, number>;
  /** Optional native tooltip text. */
  title?: string;
}

export interface BarChartProps {
  data: ReadonlyArray<BarDatum>;
  series: ReadonlyArray<BarSeries>;
  /** Show the color legend under the chart. */
  legend?: boolean;
  /** Fire on hover/click of a bar (id passed through). */
  onSelect?: (id: string) => void;
}

const sum = (values: Record<string, number>, series: ReadonlyArray<BarSeries>): number =>
  series.reduce((acc, s) => acc + (values[s.key] || 0), 0);

/** Vertical stacked-bar chart: each bar's height scales to the max total; each
 *  segment fills its share of that bar. Mirrors the dashboard's daily/time charts. */
export function BarChart({ data, series, legend = true, onSelect }: BarChartProps) {
  const max = Math.max(1, ...data.map((d) => sum(d.values, series)));
  return (
    <>
      <div className="ju-chart">
        {data.map((datum) => {
          const barTotal = sum(datum.values, series);
          const interactive = onSelect ? " ju-interactive" : "";
          return (
            <div
              key={datum.id}
              className={`ju-bar${interactive}`}
              title={datum.title}
              style={{ height: `${Math.max(3, (100 * barTotal) / max)}%` }}
              onMouseEnter={onSelect ? () => onSelect(datum.id) : undefined}
              onClick={onSelect ? () => onSelect(datum.id) : undefined}
            >
              {series.map((s) => {
                const value = datum.values[s.key] || 0;
                const height = barTotal ? (100 * value) / barTotal : 0;
                return (
                  <div
                    key={s.key}
                    className="ju-seg"
                    style={{ height: `${height}%`, background: s.color }}
                  />
                );
              })}
            </div>
          );
        })}
      </div>
      {legend && (
        <div className="ju-legend">
          {series.map((s) => (
            <span key={s.key}>
              <i className="ju-dot" style={{ background: s.color }} />
              {s.label}
            </span>
          ))}
        </div>
      )}
    </>
  );
}
