import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, EmptyState, FilterableTable, LoadingState, SegmentedControl, fmtTok, money, type ExportColumn } from "@cc-session/dashboard-ui";
import { fetchContextLedger, type LedgerBucket } from "../../api";
import { kindPills } from "./shared";

const LEDGER_PAGE_SIZE = 10;

const ledgerExportColumns: ExportColumn<LedgerBucket>[] = [
  { header: "period", value: (b) => b.label },
  { header: "starts_on", value: (b) => b.starts_on },
  { header: "ends_on", value: (b) => b.ends_on },
  { header: "sessions", value: (b) => b.session_count },
  { header: "projects", value: (b) => b.project_count },
  { header: "context_tokens_est", value: (b) => b.total_tokens },
  { header: "input_tokens", value: (b) => b.input_tokens },
  { header: "output_tokens", value: (b) => b.output_tokens },
  { header: "cache_read_tokens", value: (b) => b.cache_read_tokens },
  { header: "cache_creation_tokens", value: (b) => b.cache_creation_tokens },
  { header: "billed_tokens", value: (b) => b.billed_tokens },
  { header: "cost_usd", value: (b) => b.cost_usd },
];

/** Context lens: the context-token ledger, bucketed daily or weekly. */
export function ContextLedger() {
  const [period, setPeriod] = useState<"daily" | "weekly">("daily");
  const [page, setPage] = useState(0);
  const { data: ledger, isError, error } = useQuery({
    queryKey: ["context", "ledger", period],
    queryFn: () => fetchContextLedger(period),
  });

  if (isError) return <EmptyState>{error.message}</EmptyState>;

  const segmentedControl = (
    <SegmentedControl
      options={[
        { value: "daily", label: "Daily" },
        { value: "weekly", label: "Weekly" },
      ]}
      value={period}
      onChange={(v) => { setPeriod(v); setPage(0); }}
    />
  );

  if (!ledger) {
    return (
      <Card title="context ledger" meta="loading…">
        <div style={{ marginBottom: 12 }}>{segmentedControl}</div>
        <LoadingState>Loading ledger…</LoadingState>
      </Card>
    );
  }

  return (
    <FilterableTable
      title="context ledger"
      meta={
        `${ledger.session_count} sessions — ${fmtTok(ledger.buckets.reduce((n, b) => n + b.billed_tokens, 0))} billed tokens, ` +
        `${money(ledger.buckets.reduce((n, b) => n + b.cost_usd, 0))} · ${fmtTok(ledger.total_tokens)} estimated context`
      }
      rows={ledger.buckets}
      columns={[
        { key: "label", header: "period", render: (b) => b.label },
        { key: "sessions", header: "sessions", numeric: true, render: (b) => String(b.session_count) },
        { key: "projects", header: "projects", numeric: true, render: (b) => String(b.project_count) },
        { key: "kinds", header: "window composition (est.)", render: (b) => kindPills(b.aggregate) },
        { key: "context", header: "context (est.)", numeric: true, render: (b) => fmtTok(b.total_tokens) },
        { key: "billed", header: "billed tokens", numeric: true, render: (b) => fmtTok(b.billed_tokens) },
        { key: "cost", header: "cost", numeric: true, render: (b) => money(b.cost_usd) },
      ]}
      rowKey={(b) => b.starts_on}
      exportColumns={ledgerExportColumns}
      filename={`context-ledger-${period}`}
      pageSize={LEDGER_PAGE_SIZE}
      page={page}
      onPageChange={setPage}
    >
      <div style={{ marginBottom: 12 }}>{segmentedControl}</div>
    </FilterableTable>
  );
}
