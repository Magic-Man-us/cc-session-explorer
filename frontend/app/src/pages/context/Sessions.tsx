import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EmptyState, FilterableTable, LoadingState, type Column } from "@cc-session/dashboard-ui";
import { fetchContextSessions, type SessionRef } from "../../api";
import { toContextSession, useNavigate } from "../../nav";
import { fmtBytes, fmtWhen, matchesSession, sessionExportColumns } from "./shared";

const SESSIONS_PAGE_SIZE = 10;

/** Context lens: sessions list. Clicking a row navigates to its own page,
 *  `/context/sessions/:id` (`ContextSessionDetail`) — never expands in place. */
export function ContextSessions() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);

  const { data: sessions, isPending, isError, error } = useQuery({ queryKey: ["context", "sessions"], queryFn: fetchContextSessions });

  if (isError) return <EmptyState>{error.message}</EmptyState>;
  if (isPending) return <LoadingState>Loading sessions…</LoadingState>;

  const columns: Column<SessionRef>[] = [
    { key: "session", header: "session", render: (r) => <code>{r.session_id.slice(0, 12)}</code> },
    { key: "project", header: "project", render: (r) => r.project },
    { key: "modified", header: "last modified", render: (r) => fmtWhen(r.last_modified) },
    { key: "size", header: "size", numeric: true, render: (r) => fmtBytes(r.size_bytes) },
  ];

  // FilterableTable's meta is a static node, not a function of the filtered rows — recompute
  // here (mirrors matchesSession) so the "N of M" count in the header stays accurate.
  const filteredCount = sessions.filter((r) => matchesSession(r, query)).length;

  return (
    <FilterableTable
      title="context sessions"
      meta={`${filteredCount} of ${sessions.length} transcripts, newest first — click one to inspect`}
      rows={sessions}
      columns={columns}
      rowKey={(r) => r.session_id}
      onRowClick={(r) => navigate(toContextSession(r.session_id))}
      query={query}
      onQueryChange={setQuery}
      filterPlaceholder="Filter by session id or project"
      matches={matchesSession}
      exportColumns={sessionExportColumns}
      filename="context-sessions"
      pageSize={SESSIONS_PAGE_SIZE}
      page={page}
      onPageChange={setPage}
    />
  );
}
