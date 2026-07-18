import { SERIES, SERIES_COLORS, SERIES_LABELS, fmtTok } from "@cc-session/dashboard-ui";
import type { DashboardSnapshot } from "./api";

// App-specific composition: a total → category → model token flow diagram.
// Not a design-system primitive, so it lives in the app and reuses the DS token colors.

const flowWidth = (value: number, max: number): number => Math.max(2, (44 * (value || 0)) / Math.max(max, 1));

export function Sankey({ data }: { data: DashboardSnapshot }) {
  const tokens = data.totals.tokens;
  const grandTotal = tokens.total_tokens;

  const categories = SERIES.map((key, index) => ({
    key,
    label: SERIES_LABELS[key],
    value: tokens[key] || 0,
    color: SERIES_COLORS[key],
    y: 70 + index * 70,
  })).filter((category) => category.value > 0);

  const topModels = data.models.slice(0, 6).map((model, index) => ({
    label: model.model,
    tokens: model.tokens,
    value: model.tokens.total_tokens,
    y: 46 + index * 48,
  }));

  return (
    <>
      <svg viewBox="0 0 960 340" role="img" aria-label="Token distribution Sankey" style={{ width: "100%", minHeight: 360, display: "block" }}>
        {categories.map((category) =>
          topModels.map((model) => {
            const value = model.tokens[category.key] || 0;
            if (value <= 0) return null;
            return (
              <path
                key={`${category.key}-${model.label}`}
                d={`M 490 ${category.y} C 580 ${category.y} 650 ${model.y} 758 ${model.y}`}
                stroke={category.color}
                strokeWidth={flowWidth(value, grandTotal)}
                strokeOpacity={0.3}
                fill="none"
                strokeLinecap="round"
              />
            );
          }),
        )}

        {categories.map((category) => (
          <g key={category.key}>
            <path
              d={`M 176 170 C 250 170 262 ${category.y} 338 ${category.y}`}
              stroke={category.color}
              strokeWidth={flowWidth(category.value, grandTotal)}
              strokeOpacity={0.42}
              fill="none"
              strokeLinecap="round"
            />
            <rect x={346} y={category.y - 22} width={142} height={44} rx={8} fill="var(--panel-2)" stroke="var(--line)" />
            <text x={360} y={category.y - 2} fill="var(--text)" fontSize={12}>
              {category.label}
            </text>
            <text x={360} y={category.y + 15} fill="var(--muted)" fontSize={11}>
              {fmtTok(category.value)}
            </text>
          </g>
        ))}

        {topModels.map((model) => (
          <g key={model.label}>
            <rect x={760} y={model.y - 18} width={166} height={38} rx={8} fill="var(--panel-2)" stroke="var(--line)" />
            <text x={772} y={model.y - 1} fill="var(--text)" fontSize={12}>
              {model.label.slice(0, 24)}
            </text>
            <text x={772} y={model.y + 14} fill="var(--muted)" fontSize={11}>
              {fmtTok(model.value)}
            </text>
          </g>
        ))}

        <rect x={32} y={136} width={142} height={68} rx={8} fill="var(--panel-2)" stroke="var(--line)" />
        <text x={48} y={164} fill="var(--text)" fontSize={12}>
          all tokens
        </text>
        <text x={48} y={184} fill="var(--muted)" fontSize={11}>
          {fmtTok(grandTotal)}
        </text>
      </svg>
      <div className="ju-legend">
        {categories.map((category) => (
          <span key={category.key}>
            <i className="ju-dot" style={{ background: category.color }} />
            {category.label}
          </span>
        ))}
      </div>
    </>
  );
}
