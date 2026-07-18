import { Button, Card, downloadJSON, fmtInt, fmtTok } from "@cc-session/dashboard-ui";
import type { DashboardSnapshot } from "../api";
import { TokenBuckets } from "../shared";

export function Data({ data }: { data: DashboardSnapshot }) {
  const s = data.source;
  const t = data.totals;
  return (
    <div style={{ display: "grid", gap: 14, gridTemplateColumns: "minmax(0,1fr) minmax(0,1fr)" }}>
      <Card title="token accounting" meta="exact fields copied from message.usage">
        <TokenBuckets tokens={t.tokens} />
      </Card>
      <Card
        title="transcript coverage"
        meta={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
            <span>{`${s.name} · ${(s.first_timestamp || "").slice(0, 10)} to ${(s.last_timestamp || "").slice(0, 10)}`}</span>
            <Button variant="ghost" onClick={() => downloadJSON("data-source", { source: s, totals: t })}>
              Export JSON
            </Button>
          </span>
        }
      >
        <table className="ju-table">
          <tbody>
            <tr><th>database</th><td className="ju-clip">{s.db_path}</td></tr>
            <tr><th>transcript files</th><td className="ju-num">{fmtInt(s.transcript_files)}</td></tr>
            <tr><th>all records</th><td className="ju-num">{fmtInt(s.total_records)}</td></tr>
            <tr><th>assistant records</th><td className="ju-num">{fmtInt(s.assistant_records)}</td></tr>
            <tr><th>assistant usage rows</th><td className="ju-num">{fmtInt(s.assistant_usage_rows)}</td></tr>
            <tr><th>unique usage turns</th><td className="ju-num">{fmtInt(s.unique_usage_turns)}</td></tr>
            <tr><th>duplicate rows skipped</th><td className="ju-num">{fmtInt(s.duplicate_usage_rows)}</td></tr>
            <tr><th>raw row tokens</th><td className="ju-num">{fmtTok(t.raw_tokens.total_tokens)}</td></tr>
            <tr><th>corrected tokens</th><td className="ju-num">{fmtTok(t.tokens.total_tokens)}</td></tr>
          </tbody>
        </table>
      </Card>
    </div>
  );
}
