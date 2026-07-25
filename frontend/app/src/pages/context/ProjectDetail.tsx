import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EmptyState, FilterableTable, LoadingState, fmtTok, type ExportColumn } from "@cc-session/dashboard-ui";
import { fetchContextProject, type SessionSummary } from "../../api";
import { sessionLinkColumn } from "../../components/columns";
import { toContextSession, useNavigate } from "../../nav";
import { useProviderScope } from "../../provider";
import { kindPills } from "./shared";

const PROJECT_SESSIONS_PAGE_SIZE = 10;

const projectSessionExportColumns: ExportColumn<SessionSummary>[] = [
  { header: "session_id", value: (s) => s.ref.session_id },
  { header: "provider", value: (s) => s.ref.provider },
  { header: "tokens", value: (s) => s.total_tokens },
  { header: "window_used_pct", value: (s) => Number((s.fraction_used * 100).toFixed(1)) },
];

/** One project's per-session context-window breakdown. Its own page:
 *  `/context/projects/:project`. */
export function ContextProjectDetail({ project }: { project: string }) {
  const navigate = useNavigate();
  const provider = useProviderScope();
  const [page, setPage] = useState(0);
  const { data: breakdown, isPending, isError, error } = useQuery({
    queryKey: ["context", "project", project, provider],
    queryFn: () => fetchContextProject(project, undefined, undefined, provider),
  });

  useEffect(() => setPage(0), [provider]);

  if (isError) return <EmptyState>{error.message}</EmptyState>;
  if (isPending) return <LoadingState>Loading breakdown…</LoadingState>;

  return (
    <FilterableTable
      title={`context breakdown — ${breakdown.project}`}
      meta={`${fmtTok(breakdown.total_tokens)} tokens across ${breakdown.session_count} sessions`}
      rows={breakdown.sessions}
      columns={[
        sessionLinkColumn<SessionSummary>({ idOf: (s) => s.ref.session_id, onClick: (s) => navigate(toContextSession(s.ref.session_id)) }),
        { key: "provider", header: "provider", render: (s) => s.ref.provider },
        { key: "kinds", header: "kinds", render: (s) => kindPills(s.kinds) },
        { key: "tokens", header: "tokens", numeric: true, render: (s) => fmtTok(s.total_tokens) },
        { key: "window", header: "window used", numeric: true, render: (s) => `${(s.fraction_used * 100).toFixed(1)}%` },
      ]}
      rowKey={(s) => s.ref.session_id}
      exportColumns={projectSessionExportColumns}
      filename={`context-project-${breakdown.project}`}
      pageSize={PROJECT_SESSIONS_PAGE_SIZE}
      page={page}
      onPageChange={setPage}
    >
      <p style={{ margin: "0 0 12px" }}>{kindPills(breakdown.aggregate)}</p>
    </FilterableTable>
  );
}
