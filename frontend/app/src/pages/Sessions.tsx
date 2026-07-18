import { FilterableTable, type Column, type ExportColumn } from "@cc-session/dashboard-ui";
import type { RecentSession } from "../api";
import { costColumn, modelLinkColumn, projectLinkColumn, sessionLinkColumn, tokensColumn, turnsColumn } from "../components/columns";
import { toContextSession, toModels, toProjects, useNavigate } from "../nav";

const SESSIONS_PAGE_SIZE = 10;

const matches = (row: RecentSession, query: string): boolean =>
  [row.id, row.first_prompt, row.project, row.model]
    .filter(Boolean)
    .join(" ")
    .toLowerCase()
    .includes(query.toLowerCase());

const exportColumns: ExportColumn<RecentSession>[] = [
  { header: "session_id", value: (r) => r.id },
  { header: "started_at", value: (r) => r.started_at },
  { header: "last_seen_at", value: (r) => r.last_seen_at },
  { header: "first_prompt", value: (r) => r.first_prompt },
  { header: "project", value: (r) => r.project },
  { header: "model", value: (r) => r.model },
  { header: "tokens", value: (r) => r.tokens.total_tokens },
  { header: "input_tokens", value: (r) => r.tokens.input_tokens },
  { header: "output_tokens", value: (r) => r.tokens.output_tokens },
  { header: "cache_read_tokens", value: (r) => r.tokens.cache_read_tokens },
  { header: "cache_creation_tokens", value: (r) => r.tokens.cache_creation_tokens },
  { header: "cost_usd", value: (r) => r.notional_cost_usd },
  { header: "turns", value: (r) => r.turns },
];

export function Sessions({
  rows,
  query,
  onQueryChange,
}: {
  rows: RecentSession[];
  query: string;
  onQueryChange: (value: string) => void;
}) {
  const navigate = useNavigate();

  const projectColumn = projectLinkColumn<RecentSession>({
    projectOf: (r) => r.project,
    onClick: (project) => navigate(toProjects(project)),
  });

  const columns: Column<RecentSession>[] = [
    sessionLinkColumn<RecentSession>({
      idOf: (r) => r.id,
      onClick: (r) => navigate(toContextSession(r.id)),
      extra: (r) => <div className="ju-muted">{(r.last_seen_at || r.started_at || "").slice(0, 16).replace("T", " ")}</div>,
    }),
    {
      key: "prompt",
      header: "prompt / project",
      render: (r) => (
        <>
          <div className="ju-clip">{r.first_prompt || "(transcript-only session)"}</div>
          {projectColumn.render(r)}
        </>
      ),
    },
    modelLinkColumn<RecentSession>({ modelOf: (r) => r.model, onClick: (model) => navigate(toModels(model)) }),
    tokensColumn<RecentSession>((r) => r.tokens.total_tokens),
    costColumn<RecentSession>((r) => r.notional_cost_usd),
    turnsColumn<RecentSession>((r) => r.turns),
  ];

  return (
    <FilterableTable
      title="sessions"
      rows={rows}
      columns={columns}
      rowKey={(r) => r.id}
      query={query}
      onQueryChange={onQueryChange}
      filterPlaceholder="Filter sessions"
      matches={matches}
      exportColumns={exportColumns}
      filename="sessions"
      pageSize={SESSIONS_PAGE_SIZE}
    />
  );
}
