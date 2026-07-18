import {
  FilterableTable,
  LinkButton,
  fmtInt,
  fmtTok,
  type Column,
  type ExportColumn,
  type TokenBreakdown,
} from "@cc-session/dashboard-ui";
import { costColumn, tokensColumn } from "./columns";
import { toSessions, useNavigate } from "../nav";

const USAGE_TABLE_PAGE_SIZE = 10;

interface UsageRow {
  tokens: TokenBreakdown;
  sessions: number;
  notional_cost_usd: number;
}

export function UsageTable<Row extends UsageRow>({
  rows,
  label,
  title,
  subtitle,
  header,
  query,
  onQueryChange,
  filename,
}: {
  rows: Row[];
  label: (row: Row) => string;
  title: string;
  subtitle: string;
  header: string;
  query: string;
  onQueryChange: (value: string) => void;
  filename: string;
}) {
  const navigate = useNavigate();

  const exportColumns: ExportColumn<Row>[] = [
    { header, value: label },
    { header: "tokens", value: (r) => r.tokens.total_tokens },
    { header: "output_tokens", value: (r) => r.tokens.output_tokens },
    { header: "cache_read_tokens", value: (r) => r.tokens.cache_read_tokens },
    { header: "cache_creation_tokens", value: (r) => r.tokens.cache_creation_tokens },
    { header: "cost_usd", value: (r) => r.notional_cost_usd },
    { header: "sessions", value: (r) => r.sessions },
  ];

  const columns: Column<Row>[] = [
    {
      key: "label",
      header,
      render: (r) => (
        <LinkButton className="ju-clip" onClick={() => navigate(toSessions(label(r)))}>
          {label(r)}
        </LinkButton>
      ),
    },
    tokensColumn((r) => r.tokens.total_tokens),
    { key: "output", header: "output", numeric: true, render: (r) => fmtTok(r.tokens.output_tokens) },
    { key: "cache_read", header: "cache read", numeric: true, render: (r) => fmtTok(r.tokens.cache_read_tokens) },
    costColumn((r) => r.notional_cost_usd),
    { key: "sessions", header: "sessions", numeric: true, render: (r) => fmtInt(r.sessions) },
  ];

  return (
    <FilterableTable
      title={title}
      meta={subtitle}
      rows={rows}
      columns={columns}
      rowKey={label}
      query={query}
      onQueryChange={onQueryChange}
      filterPlaceholder={`Filter ${header}s`}
      matches={(r, q) => label(r).toLowerCase().includes(q.toLowerCase())}
      exportColumns={exportColumns}
      filename={filename}
      pageSize={USAGE_TABLE_PAGE_SIZE}
    />
  );
}
