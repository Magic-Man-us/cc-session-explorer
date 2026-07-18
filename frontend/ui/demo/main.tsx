import { createRoot } from "react-dom/client";
import {
  BarChart,
  Button,
  Card,
  DataTable,
  EmptyState,
  Input,
  KpiCard,
  Pill,
  Root,
  SegmentedControl,
  SERIES,
  SERIES_COLORS,
  SERIES_LABELS,
  Sidebar,
  StatBar,
  fmtTok,
  money,
  type BarDatum,
} from "../src";

const tokens = {
  input_tokens: 4_200_000,
  output_tokens: 980_000,
  cache_read_tokens: 61_400_000,
  cache_creation_tokens: 7_300_000,
};

const statRows = SERIES.map((key) => ({
  label: SERIES_LABELS[key],
  value: tokens[key],
  color: SERIES_COLORS[key],
}));

const series = SERIES.map((key) => ({
  key,
  label: SERIES_LABELS[key],
  color: SERIES_COLORS[key],
}));

const days: BarDatum[] = Array.from({ length: 24 }, (_, i) => {
  const scale = 0.4 + 0.6 * Math.abs(Math.sin(i / 3));
  return {
    id: `2026-06-${String(i + 1).padStart(2, "0")}`,
    title: `day ${i + 1}`,
    values: {
      cache_read_tokens: Math.round(tokens.cache_read_tokens * scale * 0.02),
      cache_creation_tokens: Math.round(tokens.cache_creation_tokens * scale * 0.02),
      input_tokens: Math.round(tokens.input_tokens * scale * 0.02),
      output_tokens: Math.round(tokens.output_tokens * scale * 0.02),
    },
  };
});

interface ModelRow {
  model: string;
  total: number;
  cost: number;
  sessions: number;
}
const modelRows: ModelRow[] = [
  { model: "claude-opus-4-8", total: 48_200_000, cost: 214.5, sessions: 38 },
  { model: "claude-sonnet-5", total: 21_900_000, cost: 62.1, sessions: 51 },
  { model: "claude-haiku-4-5", total: 3_100_000, cost: 4.2, sessions: 12 },
];

function Showcase() {
  return (
    <Root style={{ display: "grid", gridTemplateColumns: "248px 1fr" }}>
      <Sidebar
        brand="cc-session"
        subtitle="local session ledger"
        active="overview"
        onSelect={() => {}}
        items={[
          { value: "overview", label: "Overview" },
          { value: "time", label: "Time" },
          { value: "live", label: "Live" },
          { value: "sessions", label: "Sessions" },
          { value: "models", label: "Models" },
        ]}
      />
      <main style={{ padding: 24, minWidth: 0, display: "grid", gap: 14 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 24 }}>Session cost and token flow</h1>
            <div style={{ color: "var(--muted)", fontSize: 12, marginTop: 6 }}>
              Generated 2026-07-03 17:20
            </div>
          </div>
          <Button>Refresh</Button>
        </div>

        <div style={{ display: "grid", gap: 14, gridTemplateColumns: "repeat(4, minmax(0,1fr))" }}>
          <KpiCard label="corrected tokens" value={fmtTok(73_880_000)} hint="1,204 assistant messages" />
          <KpiCard label="notional cost" value={money(280.8)} hint="API-list estimate" />
          <KpiCard label="sessions" value="101" hint="with usage records" />
          <KpiCard label="cache hit rate" value="83.1%" hint="read / context tokens" />
        </div>

        <Card title="tokens per day" meta="last 24 days">
          <BarChart data={days} series={series} onSelect={() => {}} />
        </Card>

        <div style={{ display: "grid", gap: 14, gridTemplateColumns: "1.15fr .85fr" }}>
          <Card title="where tokens went" meta={`${fmtTok(73_880_000)} total`}>
            <StatBar rows={statRows} />
          </Card>
          <Card title="controls" meta="primitives">
            <div style={{ display: "grid", gap: 12 }}>
              <SegmentedControl
                value="daily"
                onChange={() => {}}
                options={[
                  { value: "weekly", label: "Weekly" },
                  { value: "daily", label: "Daily" },
                  { value: "hourly", label: "Hourly" },
                ]}
              />
              <Input placeholder="Filter sessions" />
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <Pill>live</Pill>
                <Button variant="ghost">Ghost</Button>
              </div>
            </div>
          </Card>
        </div>

        <Card title="model usage" meta="priced by model family">
          <DataTable
            rows={modelRows}
            rowKey={(r) => r.model}
            onRowClick={() => {}}
            selectedKey="claude-opus-4-8"
            columns={[
              { key: "model", header: "model", render: (r) => <span className="ju-mono">{r.model}</span> },
              { key: "total", header: "tokens", numeric: true, render: (r) => fmtTok(r.total) },
              { key: "cost", header: "cost", numeric: true, render: (r) => money(r.cost) },
              { key: "sessions", header: "sessions", numeric: true, render: (r) => r.sessions },
            ]}
          />
        </Card>

        <Card title="empty" meta="no data">
          <EmptyState>No usage in range</EmptyState>
        </Card>
      </main>
    </Root>
  );
}

createRoot(document.getElementById("root")!).render(<Showcase />);
