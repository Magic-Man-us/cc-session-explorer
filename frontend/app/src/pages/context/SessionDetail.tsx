import { useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Button, EmptyState, ExportButtons, KpiCard, LoadingState, Pill, SankeyChart, fmtTok } from "@cc-session/dashboard-ui";
import {
  contextInvestigationUrl,
  contextSankeyUrl,
  fetchContextGrouped,
  fetchContextSankeyData,
  fetchSessionTranscript,
} from "../../api";
import { TimelineEventRow } from "../../shared";
import { toSessions, useNavigate } from "../../nav";
import { KIND_ACCENT, assignSankeyColors, groupExportColumns } from "./shared";

/** Everything about one session — grouped context chains, the full raw event-by-event
 *  transcript, and the cross-links out. Its own page: `/context/sessions/:id`. */
export function ContextSessionDetail({ session }: { session: string }) {
  const navigate = useNavigate();
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  const {
    data: sankey,
    isPending: sankeyPending,
    isError: sankeyIsError,
    error: sankeyError,
  } = useQuery({ queryKey: ["context", "session", session, "sankey"], queryFn: () => fetchContextSankeyData(session) });

  const {
    data: groups,
    isPending: groupsPending,
    isError: groupsIsError,
    error: groupsError,
  } = useQuery({ queryKey: ["context", "session", session, "grouped"], queryFn: () => fetchContextGrouped(session) });

  const {
    data: transcriptData,
    isPending: transcriptPending,
    isError: transcriptIsError,
    error: transcriptError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["context", "session", session, "transcript"],
    queryFn: ({ pageParam }) => fetchSessionTranscript(session, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => (lastPage.truncated ? lastPage.cursor : undefined),
  });
  const events = transcriptData?.pages.flatMap((p) => p.events);
  const sankeyColors = sankey ? assignSankeyColors(sankey.graphs) : {};
  const sortedGroups = groups ? [...groups].sort((a, b) => b.tokens - a.tokens) : undefined;

  return (
    <div style={{ display: "grid", gap: 20, padding: "4px 0" }}>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Button onClick={() => navigate(toSessions(session))}>View cost & usage ↗</Button>
      </div>

      <div>
        {sankeyIsError && <EmptyState>{sankeyError.message}</EmptyState>}
        {sankeyPending && <LoadingState>Loading token flow…</LoadingState>}
        {sankey && (
          <>
            <div style={{ display: "grid", gap: 10, gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", marginBottom: 12 }}>
              {sankey.stats.map((s) => (
                <KpiCard key={s.label} label={s.label} value={s.value} />
              ))}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 8 }}>
              <span className="ju-muted" style={{ fontSize: 12 }}>token, cost, and tool-activity flow for this session</span>
              <a className="ju-link" href={contextSankeyUrl(session)} target="_blank" rel="noreferrer">
                Open standalone Sankey page ↗
              </a>
            </div>
            <div className="ju-sankey-grid">
              {sankey.graphs.map((g) => (
                <SankeyChart key={g.title} graph={g} colors={sankeyColors} />
              ))}
            </div>
          </>
        )}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <a
          className="ju-button ju-button--ghost"
          href={contextInvestigationUrl(session, "markdown")}
          download={`investigation-${session.slice(0, 12)}.md`}
        >
          Download investigation record (Markdown)
        </a>
        <a
          className="ju-button ju-button--ghost"
          href={contextInvestigationUrl(session, "json")}
          download={`investigation-${session.slice(0, 12)}.json`}
        >
          Download investigation record (JSON)
        </a>
      </div>

      <div>
        <div className="ju-muted" style={{ fontSize: 12, marginBottom: 8, display: "flex", justifyContent: "space-between" }}>
          <span>context chains — grouped by what filled the window, largest first</span>
          {groups && <ExportButtons rows={groups} columns={groupExportColumns} filename={`context-chains-${session.slice(0, 12)}`} />}
        </div>
        {groupsIsError && <EmptyState>{groupsError.message}</EmptyState>}
        {groupsPending && <LoadingState>Loading chains…</LoadingState>}
        {sortedGroups && (
          <div className="ju-chain-grid">
            {sortedGroups.map((g) => {
              const key = `${g.kind}:${g.label}`;
              const open = expandedGroup === key;
              return (
                <div
                  key={key}
                  className={open ? "ju-chain-card ju-chain-open" : "ju-chain-card"}
                  onClick={() => setExpandedGroup((prev) => (prev === key ? null : key))}
                >
                  <div className="ju-chain-top">
                    <Pill accent={KIND_ACCENT[g.kind]} dot={false}>{g.kind}</Pill>
                    <span className="ju-chain-tokens">{fmtTok(g.tokens)}</span>
                  </div>
                  <div className="ju-chain-label">{g.label}</div>
                  <div className="ju-chain-meta">{g.count} event{g.count === 1 ? "" : "s"}</div>
                  {open && (
                    <div className="ju-chain-expanded">
                      {g.events.map((event, index) => (
                        <div key={index} style={{ display: "flex", gap: 10, alignItems: "baseline", fontSize: 12.5 }}>
                          <span className="ju-muted" style={{ minWidth: 56, textAlign: "right" }}>
                            {fmtTok(event.tokens)}
                          </span>
                          <span>{event.label}</span>
                          {event.detail && <span className="ju-muted">— {event.detail}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div>
        <div className="ju-muted" style={{ fontSize: 12, marginBottom: 6 }}>
          full transcript — every text, thinking, tool call, and tool result, in order
        </div>
        {transcriptIsError && <EmptyState>{transcriptError.message}</EmptyState>}
        {transcriptPending && <LoadingState>Loading transcript…</LoadingState>}
        {events && events.length === 0 && <EmptyState>No raw events captured for this session.</EmptyState>}
        {events && events.length > 0 && (
          <div className="ju-timeline" style={{ maxHeight: "70vh" }}>
            {events.map((event, index) => (
              <TimelineEventRow key={index} event={event} session={session} />
            ))}
          </div>
        )}
        {hasNextPage && (
          <button className="ju-tl-more" onClick={() => fetchNextPage()} disabled={isFetchingNextPage} style={{ marginTop: 8 }}>
            {isFetchingNextPage ? "loading…" : "load more"}
          </button>
        )}
      </div>
    </div>
  );
}
