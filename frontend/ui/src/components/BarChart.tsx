import { fmtTok } from "../format";

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
  /** Axis titles rendered with the numeric and categorical scales. */
  xAxisLabel?: string;
  yAxisLabel?: string;
  /** Preview a bar without committing an action. */
  onHover?: (id: string) => void;
  /** Activate a bar by click, Enter, or Space. */
  onSelect?: (id: string) => void;
}

const sum = (values: Record<string, number>, series: ReadonlyArray<BarSeries>): number =>
  series.reduce((acc, s) => acc + (values[s.key] || 0), 0);

const tickIndexes = (length: number): number[] => {
  if (length <= 1) return [0];
  const count = Math.min(5, length);
  return [
    ...new Set(
      Array.from({ length: count }, (_, index) =>
        Math.round((index * (length - 1)) / (count - 1)),
      ),
    ),
  ];
};

/** Vertical stacked-bar chart with explicit token and bucket axes. */
export function BarChart({
  data,
  series,
  legend = true,
  xAxisLabel = "Time bucket",
  yAxisLabel = "Tokens",
  onHover,
  onSelect,
}: BarChartProps) {
  const max = Math.max(1, ...data.map((d) => sum(d.values, series)));
  const xTicks = tickIndexes(data.length);
  return (
    <>
      <div className="ju-chart-scroll">
        <div
          className="ju-chart-figure"
          role="group"
          aria-label={`${yAxisLabel} by ${xAxisLabel.toLowerCase()}`}
          style={{ minWidth: `${Math.max(360, data.length * 12)}px` }}
        >
          <div className="ju-chart-y-title">{yAxisLabel}</div>
          <div className="ju-chart-body">
            <div className="ju-chart-y-scale" aria-hidden="true">
              <span>{fmtTok(max)}</span>
              <span>{fmtTok(max / 2)}</span>
              <span>0</span>
            </div>
            <div className="ju-chart-column">
              <div className="ju-chart-plot">
                <div className="ju-chart-gridline ju-chart-gridline--top" />
                <div className="ju-chart-gridline ju-chart-gridline--middle" />
                <div className="ju-chart-gridline ju-chart-gridline--bottom" />
                <div className="ju-chart-bars">
                  {data.map((datum) => {
                    const barTotal = sum(datum.values, series);
                    const segments = series.map((s) => {
                      const value = datum.values[s.key] || 0;
                      const height = barTotal ? (100 * value) / barTotal : 0;
                      return (
                        <span
                          key={s.key}
                          className="ju-seg"
                          style={{ height: `${height}%`, background: s.color }}
                        />
                      );
                    });
                    const style = {
                      height: `${Math.max(3, (100 * barTotal) / max)}%`,
                    };
                    const label =
                      datum.title ??
                      `${datum.id}: ${fmtTok(barTotal)} ${yAxisLabel.toLowerCase()}`;
                    return onSelect ? (
                      <button
                        key={datum.id}
                        type="button"
                        className="ju-bar ju-interactive"
                        title={label}
                        aria-label={label}
                        style={style}
                        onMouseEnter={onHover ? () => onHover(datum.id) : undefined}
                        onFocus={onHover ? () => onHover(datum.id) : undefined}
                        onClick={() => onSelect(datum.id)}
                      >
                        {segments}
                      </button>
                    ) : (
                      <div
                        key={datum.id}
                        className="ju-bar"
                        title={label}
                        style={style}
                        onMouseEnter={onHover ? () => onHover(datum.id) : undefined}
                      >
                        {segments}
                      </div>
                    );
                  })}
                </div>
              </div>
              <div className="ju-chart-x-ticks" aria-hidden="true">
                {xTicks.map((index) => {
                  const datum = data[index];
                  const position =
                    data.length === 1 ? 50 : (100 * index) / (data.length - 1);
                  return (
                    <span
                      key={`${datum.id}-${index}`}
                      style={{ left: `${position}%` }}
                    >
                      {datum.id}
                    </span>
                  );
                })}
              </div>
              <div className="ju-chart-x-title">{xAxisLabel}</div>
            </div>
          </div>
        </div>
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
