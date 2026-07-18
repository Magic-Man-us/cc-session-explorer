import { useMemo, useState } from "react";
import { Button, Card, DataTable, ExportButtons, Input, Pagination, SegmentedControl, fmtInt, fmtTok, money, type ExportColumn } from "@cc-session/dashboard-ui";
import type { DashboardSnapshot, Grain, TimeUsage } from "../api";
import { toBar, usageBarChart } from "../shared";
import { toTimeBucket, useNavigate } from "../nav";

const bucketExportColumns: ExportColumn<TimeUsage>[] = [
  { header: "bucket", value: (r) => r.bucket },
  { header: "tokens", value: (r) => r.tokens.total_tokens },
  { header: "input_tokens", value: (r) => r.tokens.input_tokens },
  { header: "output_tokens", value: (r) => r.tokens.output_tokens },
  { header: "cache_read_tokens", value: (r) => r.tokens.cache_read_tokens },
  { header: "cache_creation_tokens", value: (r) => r.tokens.cache_creation_tokens },
  { header: "cost_usd", value: (r) => r.notional_cost_usd },
  { header: "turns", value: (r) => r.turns },
  { header: "sessions", value: (r) => r.sessions },
];

const BUCKET_PAGE_SIZE = 10;

const GRAINS: { value: Grain; label: string }[] = [
  { value: "weekly", label: "Weekly" },
  { value: "daily", label: "Daily" },
  { value: "hourly", label: "Hourly" },
  { value: "five_minute", label: "5 min" },
];

const bucketRows = (data: DashboardSnapshot, grain: Grain): TimeUsage[] => {
  if (grain === "weekly") return data.weekly;
  if (grain === "hourly") return data.hourly;
  if (grain === "five_minute") return data.five_minute;
  return data.daily.map((d) => ({ ...d, bucket: d.day }));
};

const parseTime = (value: string): number | null => {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const inputTime = (value: string): number | null => {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
};

export function Time({ data }: { data: DashboardSnapshot }) {
  const navigate = useNavigate();
  const [grain, setGrain] = useState<Grain>("daily");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [page, setPage] = useState(0);

  const rows = useMemo(() => bucketRows(data, grain), [data, grain]);
  const inRange = (row: TimeUsage): boolean => {
    const value = parseTime(row.bucket);
    const lo = inputTime(start);
    const hi = inputTime(end);
    if (value === null) return false;
    return (lo === null || value >= lo) && (hi === null || value <= hi);
  };
  const visible = rows.filter(inRange);
  const filteredTokens = visible.reduce((sum, r) => sum + r.tokens.total_tokens, 0);

  const bars = visible.map((r) => toBar(r.bucket, r.tokens, `${r.bucket} · ${fmtTok(r.tokens.total_tokens)} tokens · ${r.turns} turns`));
  const newestFirst = visible.slice().reverse();
  const tableRows = newestFirst.slice(page * BUCKET_PAGE_SIZE, (page + 1) * BUCKET_PAGE_SIZE);

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <Card title="time range" meta={`${fmtInt(visible.length)} buckets · ${fmtTok(filteredTokens)} tokens`}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <SegmentedControl options={GRAINS} value={grain} onChange={(v) => { setGrain(v); setPage(0); }} />
          <div style={{ width: 220 }}>
            <Input type="datetime-local" value={start} onChange={(e) => { setStart(e.target.value.trim()); setPage(0); }} />
          </div>
          <div style={{ width: 220 }}>
            <Input type="datetime-local" value={end} onChange={(e) => { setEnd(e.target.value.trim()); setPage(0); }} />
          </div>
          <Button onClick={() => { setStart(""); setEnd(""); setPage(0); }}>Clear</Button>
        </div>
        <div className="ju-muted" style={{ fontSize: 12, marginTop: 10 }}>
          Start and end are local browser times; ledger buckets are stored in UTC.
        </div>
      </Card>

      <div style={{ display: "grid", gap: 14 }}>
        <Card title={`${grain.replace("_", " ")} usage`} meta="click a bar or row">
          {usageBarChart(bars, (bucket) => navigate(toTimeBucket(grain, bucket)))}
        </Card>
        <Card
          title="bucket table"
          meta={
            <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
              <span>newest first</span>
              <ExportButtons rows={newestFirst} columns={bucketExportColumns} filename={`usage-${grain}`} />
            </span>
          }
        >
          <DataTable
            rows={tableRows}
            rowKey={(r) => r.bucket}
            onRowClick={(r) => navigate(toTimeBucket(grain, r.bucket))}
            columns={[
              { key: "bucket", header: "bucket", render: (r) => <span className="ju-mono">{r.bucket.replace("T", " ").replace("+00:00", "Z")}</span> },
              { key: "tokens", header: "tokens", numeric: true, render: (r) => fmtTok(r.tokens.total_tokens) },
              { key: "input", header: "input", numeric: true, render: (r) => fmtTok(r.tokens.input_tokens) },
              { key: "output", header: "output", numeric: true, render: (r) => fmtTok(r.tokens.output_tokens) },
              { key: "cache_read", header: "cache read", numeric: true, render: (r) => fmtTok(r.tokens.cache_read_tokens) },
              { key: "cache_write", header: "cache write", numeric: true, render: (r) => fmtTok(r.tokens.cache_creation_tokens) },
              { key: "cost", header: "cost", numeric: true, render: (r) => money(r.notional_cost_usd) },
              { key: "turns", header: "turns", numeric: true, render: (r) => fmtInt(r.turns) },
            ]}
          />
          <Pagination page={page} pageSize={BUCKET_PAGE_SIZE} total={newestFirst.length} onPageChange={setPage} />
        </Card>
      </div>
    </div>
  );
}
