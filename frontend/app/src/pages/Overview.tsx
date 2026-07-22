import { useState } from "react";
import { Button, Card, KpiCard, StatBar, downloadJSON, fmtInt, fmtTok, money } from "@cc-session/dashboard-ui";
import type { DashboardSnapshot } from "../api";
import { Sankey } from "../Sankey";
import { toSessions, useNavigate } from "../nav";
import { BucketDetailPanel, TokenBuckets, toBar, usageBarChart } from "../shared";
import { LiveTail } from "./Live";

export function Overview({ data }: { data: DashboardSnapshot }) {
  const navigate = useNavigate();
  const [day, setDay] = useState("");
  const t = data.totals;
  const days = data.daily.slice(-42).map((d) => toBar(d.day, d.tokens, `${d.day} · ${fmtTok(d.tokens.total_tokens)} tokens · ${d.sessions} sessions`));

  return (
    <div className="cc-dashboard">
      <div className="cc-kpi-grid">
        <KpiCard label="corrected tokens" value={fmtTok(t.tokens.total_tokens)} hint={`${fmtInt(t.turns)} unique assistant messages`} />
        <KpiCard label="notional cost" value={money(t.notional_cost_usd)} hint="API-list estimate" />
        <KpiCard
          label="sessions"
          value={fmtInt(t.sessions)}
          hint="with usage records — click to browse"
          onClick={() => navigate(toSessions(""))}
        />
        <KpiCard label="cache hit rate" value={`${(100 * (t.tokens.cache_hit_rate ?? 0)).toFixed(1)}%`} hint="read / context tokens" />
      </div>

      <Card title="token distribution" meta="total to category to model">
        <Sankey data={data} />
      </Card>

      <div className="cc-overview-grid cc-overview-grid--weighted">
        <Card title="tokens per day" meta="last 42 days — click a bar">
          {usageBarChart(days, setDay)}
          <div style={{ marginTop: 14 }}>
            <BucketDetailPanel grain="daily" bucket={day} hint="Click a day to inspect its sessions." />
          </div>
        </Card>
        <Card title="where tokens went" meta={`${fmtTok(t.tokens.total_tokens)} total`}>
          <TokenBuckets tokens={t.tokens} />
          <div className="ju-muted" style={{ fontSize: 12, marginTop: 10 }}>
            {data.notes.map((note, i) => (
              <div key={i}>{note}</div>
            ))}
          </div>
        </Card>
      </div>

      <div className="cc-overview-grid">
        <Card title="corrected vs raw transcript rows" meta="deduped, plus ledger history for rotated-off sessions">
          <StatBar
            rows={[
              { label: "corrected", value: t.tokens.total_tokens, color: "var(--green)" },
              { label: "raw rows (on disk)", value: t.raw_tokens.total_tokens, color: "var(--violet)" },
            ]}
          />
          <div className="ju-muted" style={{ fontSize: 12, marginTop: 10 }}>
            {fmtInt(t.duplicate_usage_rows)} repeated assistant usage rows skipped by message id.
            Corrected can exceed raw: it also includes history for sessions whose transcripts
            have since rotated off disk.
          </div>
        </Card>
        <Card
          title="data source"
          meta={
            <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
              <span>{data.source.name}</span>
              <Button variant="ghost" onClick={() => downloadJSON("dashboard-snapshot", data)}>
                Export JSON
              </Button>
            </span>
          }
        >
          <table className="ju-table">
            <tbody>
              <tr><th>database</th><td className="ju-clip">{data.source.db_path}</td></tr>
              <tr><th>records</th><td className="ju-num">{fmtInt(data.source.total_records)}</td></tr>
              <tr><th>assistant records</th><td className="ju-num">{fmtInt(data.source.assistant_records)}</td></tr>
              <tr><th>usage rows</th><td className="ju-num">{fmtInt(data.source.assistant_usage_rows)}</td></tr>
              <tr><th>unique usage turns</th><td className="ju-num">{fmtInt(data.source.unique_usage_turns)}</td></tr>
            </tbody>
          </table>
        </Card>
      </div>

      <LiveTail />
    </div>
  );
}
