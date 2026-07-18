import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, DataTable, ExportButtons, LinkButton, Pagination, fmtTok, money, type ExportColumn } from "@cc-session/dashboard-ui";
import { fetchTail, type UsageEvent } from "../api";
import { toContextSession, toModels, toProjects, useNavigate } from "../nav";

const TAIL_LIMIT = 80;
const POLL_MS = 5000;
const TAIL_PAGE_SIZE = 10;

const tailExportColumns: ExportColumn<UsageEvent>[] = [
  { header: "key", value: (r) => r.key },
  { header: "timestamp", value: (r) => r.timestamp },
  { header: "session_id", value: (r) => r.session_id },
  { header: "project", value: (r) => r.project },
  { header: "model", value: (r) => r.model },
  { header: "source_kind", value: (r) => r.source_kind },
  { header: "tokens", value: (r) => r.tokens.total_tokens },
  { header: "cost_usd", value: (r) => r.notional_cost_usd },
];

/** The most recent priced usage events across every session — a spend tail, not a
 *  transcript feed. For "what is the agent actually saying/doing right now", see the
 *  Live Feed (session picker + full raw log) instead. */
export function LiveTail() {
  const navigate = useNavigate();
  const [enabled, setEnabled] = useState(true);
  const [page, setPage] = useState(0);
  const { data: tail, isPending, isError, error } = useQuery({
    queryKey: ["live", "tail", TAIL_LIMIT],
    queryFn: () => fetchTail(TAIL_LIMIT),
    refetchInterval: enabled ? POLL_MS : false,
  });
  const events = tail?.events ?? [];
  const pageEvents = events.slice(page * TAIL_PAGE_SIZE, (page + 1) * TAIL_PAGE_SIZE);

  const status = isPending
    ? "Waiting"
    : isError
      ? error.message
      : "Updated " + (tail?.generated_at.slice(11, 19) ?? "");

  return (
    <Card
      title="recent spend"
      meta={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
          <span>{status}</span>
          <label style={{ cursor: "pointer" }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /> auto-refresh
          </label>
          <ExportButtons rows={events} columns={tailExportColumns} filename="live-tail" />
        </span>
      }
    >
      <div className="ju-muted" style={{ fontSize: 12, marginBottom: 8 }}>
        The last {TAIL_LIMIT} priced usage events, across every session — {money(tail?.total_cost_usd)} total.
      </div>
      <DataTable
        rows={pageEvents}
        rowKey={(r) => r.key}
        columns={[
          {
            key: "time",
            header: "time",
            render: (r) => (
              <>
                <div className="ju-mono">{(r.timestamp || "").slice(0, 19).replace("T", " ")}</div>
                <div className="ju-muted">{r.source_kind}</div>
              </>
            ),
          },
          {
            key: "session",
            header: "session / project",
            render: (r) => {
              const sessionId = r.session_id;
              const project = r.project;
              return (
                <>
                  {sessionId ? (
                    <LinkButton className="ju-mono" onClick={() => navigate(toContextSession(sessionId))}>
                      {sessionId.slice(0, 12)}
                    </LinkButton>
                  ) : (
                    <div className="ju-mono">—</div>
                  )}
                  {project && (
                    <div className="ju-muted ju-clip">
                      <LinkButton className="ju-muted ju-clip" onClick={() => navigate(toProjects(project))}>
                        {project}
                      </LinkButton>
                    </div>
                  )}
                </>
              );
            },
          },
          {
            key: "model",
            header: "model",
            render: (r) => {
              const model = r.model;
              return model ? <LinkButton onClick={() => navigate(toModels(model))}>{model}</LinkButton> : null;
            },
          },
          { key: "tokens", header: "tokens", numeric: true, render: (r) => fmtTok(r.tokens.total_tokens) },
          { key: "cost", header: "cost", numeric: true, render: (r) => money(r.notional_cost_usd) },
        ]}
      />
      <Pagination page={page} pageSize={TAIL_PAGE_SIZE} total={events.length} onPageChange={setPage} />
    </Card>
  );
}
