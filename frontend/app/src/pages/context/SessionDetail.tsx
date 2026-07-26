import { useState, type ReactNode } from "react";
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
import { useProviderScope } from "../../provider";
import { ContextTraceDashboard } from "./ContextTraceDashboard";
import { KIND_ACCENT, assignSankeyColors, groupExportColumns } from "./shared";

function SectionHeader({
  id,
  title,
  description,
  actions,
}: {
  id: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="cc-section-heading">
      <div>
        <h2 id={id}>{title}</h2>
        <p>{description}</p>
      </div>
      {actions && <div className="cc-section-actions">{actions}</div>}
    </div>
  );
}

/** Everything about one session — grouped context chains, the full raw event-by-event
 *  transcript, and the cross-links out. Its own page: `/context/sessions/:id`. */
export function ContextSessionDetail({ session }: { session: string }) {
  const navigate = useNavigate();
  const provider = useProviderScope();
  const [expandedGroup, setExpandedGroup] = useState<string | null>(null);

  const {
    data: sankey,
    isPending: sankeyPending,
    isError: sankeyIsError,
    error: sankeyError,
  } = useQuery({
    queryKey: ["context", "session", session, "sankey", provider],
    queryFn: () => fetchContextSankeyData(session, provider),
  });

  const {
    data: groups,
    isPending: groupsPending,
    isError: groupsIsError,
    error: groupsError,
  } = useQuery({
    queryKey: ["context", "session", session, "grouped", provider],
    queryFn: () => fetchContextGrouped(session, provider),
  });

  const {
    data: transcriptData,
    isPending: transcriptPending,
    isError: transcriptIsError,
    error: transcriptError,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery({
    queryKey: ["context", "session", session, "transcript", provider],
    queryFn: ({ pageParam }) => fetchSessionTranscript(session, pageParam, provider),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (lastPage) => (lastPage.truncated ? lastPage.cursor : undefined),
  });
  const events = transcriptData?.pages.flatMap((p) => p.events);
  const sankeyColors = sankey ? assignSankeyColors(sankey.graphs) : {};
  const sortedGroups = groups ? [...groups].sort((a, b) => b.tokens - a.tokens) : undefined;

  return (
    <div className="cc-session-detail">
      <ContextTraceDashboard session={session} />

      <nav className="cc-session-toolbar" aria-label="Session actions">
        <Button onClick={() => navigate(toSessions(session))}>View cost & usage ↗</Button>
        <a
          className="ju-button ju-button--ghost"
          href={contextInvestigationUrl(session, "markdown", provider)}
          download={`investigation-${session.slice(0, 12)}.md`}
        >
          Export Markdown
        </a>
        <a
          className="ju-button ju-button--ghost"
          href={contextInvestigationUrl(session, "json", provider)}
          download={`investigation-${session.slice(0, 12)}.json`}
        >
          Export JSON
        </a>
      </nav>

      <section className="cc-session-section" aria-labelledby="session-flow-heading">
        <SectionHeader
          id="session-flow-heading"
          title="Session flow"
          description="Token, cost, and tool activity move from source to outcome; ribbon width represents volume."
          actions={
            <a className="ju-link" href={contextSankeyUrl(session, provider)} target="_blank" rel="noreferrer">
              Open standalone Sankey ↗
            </a>
          }
        />
        {sankeyIsError && <EmptyState>{sankeyError.message}</EmptyState>}
        {sankeyPending && <LoadingState>Loading token flow…</LoadingState>}
        {sankey && (
          <>
            <div className="cc-flow-kpis">
              {sankey.stats.map((s) => (
                <KpiCard key={s.label} label={s.label} value={s.value} />
              ))}
            </div>
            <div className="ju-sankey-grid">
              {sankey.graphs.map((g) => (
                <SankeyChart key={g.title} graph={g} colors={sankeyColors} />
              ))}
            </div>
          </>
        )}
      </section>

      <section className="cc-session-section" aria-labelledby="context-chains-heading">
        <SectionHeader
          id="context-chains-heading"
          title="Context chains"
          description="What filled the context window, grouped and ordered from largest to smallest."
          actions={
            groups
              ? <ExportButtons rows={groups} columns={groupExportColumns} filename={`context-chains-${session.slice(0, 12)}`} />
              : undefined
          }
        />
        {groupsIsError && <EmptyState>{groupsError.message}</EmptyState>}
        {groupsPending && <LoadingState>Loading chains…</LoadingState>}
        {sortedGroups && (
          <div className="ju-chain-grid">
            {sortedGroups.map((g) => {
              const key = `${g.kind}:${g.label}`;
              const open = expandedGroup === key;
              return (
                <button
                  type="button"
                  key={key}
                  className={open ? "ju-chain-card ju-chain-open" : "ju-chain-card"}
                  onClick={() => setExpandedGroup((prev) => (prev === key ? null : key))}
                  aria-expanded={open}
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
                </button>
              );
            })}
          </div>
        )}
      </section>

      <section className="cc-session-section" aria-labelledby="full-transcript-heading">
        <SectionHeader
          id="full-transcript-heading"
          title="Full transcript"
          description="Every text block, reasoning block, tool call, and tool result in chronological order."
        />
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
      </section>
    </div>
  );
}
