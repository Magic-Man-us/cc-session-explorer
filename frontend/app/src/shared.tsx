import { useEffect, useState } from "react";
import {
  BarChart,
  Card,
  DataTable,
  EmptyState,
  ExportButtons,
  JsonOrText,
  Pagination,
  StatBar,
  SERIES,
  SERIES_COLORS,
  SERIES_LABELS,
  fmtInt,
  fmtTok,
  money,
  type BarDatum,
  type ExportColumn,
  type StatBarRow,
  type TokenBreakdown,
} from "@cc-session/dashboard-ui";
import {
  fetchBlock,
  fetchBucket,
  fetchSessionTimeline,
  type BucketDetail,
  type BucketSessionUsage,
  type SessionTimeline,
  type TimelineEvent,
} from "./api";
import { costColumn, modelLinkColumn, projectLinkColumn, sessionLinkColumn, tokensColumn, turnsColumn } from "./components/columns";
import { toContextSession, toModels, toProjects, useNavigate } from "./nav";

const BUCKET_SESSIONS_PAGE_SIZE = 10;

const bucketSessionExportColumns: ExportColumn<BucketSessionUsage>[] = [
  { header: "session_id", value: (r) => r.session_id },
  { header: "project", value: (r) => r.project },
  { header: "model", value: (r) => r.model },
  { header: "first_seen_at", value: (r) => r.first_seen_at },
  { header: "last_seen_at", value: (r) => r.last_seen_at },
  { header: "tokens", value: (r) => r.tokens.total_tokens },
  { header: "cost_usd", value: (r) => r.notional_cost_usd },
  { header: "turns", value: (r) => r.turns },
];

export const series = SERIES.map((key) => ({ key, label: SERIES_LABELS[key], color: SERIES_COLORS[key] }));

/** The four token categories as StatBar rows, scaled to the largest. */
export const tokenRows = (tokens: TokenBreakdown): StatBarRow[] =>
  SERIES.map((key) => ({ label: SERIES_LABELS[key], value: tokens[key] || 0, color: SERIES_COLORS[key] }));

export function TokenBuckets({ tokens }: { tokens: TokenBreakdown }) {
  return <StatBar rows={tokenRows(tokens)} />;
}

/** A usage row (day/bucket) as a stacked BarChart datum. */
export const toBar = (id: string, tokens: TokenBreakdown, title: string): BarDatum => ({
  id,
  title,
  values: {
    cache_read_tokens: tokens.cache_read_tokens || 0,
    cache_creation_tokens: tokens.cache_creation_tokens || 0,
    input_tokens: tokens.input_tokens || 0,
    output_tokens: tokens.output_tokens || 0,
  },
});

const clock = (ts: string | null): string => {
  if (!ts) return "";
  const parsed = new Date(ts);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toISOString().slice(11, 19);
};

interface EventDisplay {
  bodyClass: string;
  label: string;
  mono: boolean;
  text: string;
}

const display = (event: TimelineEvent): EventDisplay => {
  switch (event.kind) {
    case "text":
      return { bodyClass: `ju-tl-${event.role}`, label: event.role, mono: false, text: event.text };
    case "thinking":
      return { bodyClass: "ju-tl-thinking", label: "thinking", mono: false, text: event.thinking };
    case "tool_use":
      return {
        bodyClass: "ju-tl-tool_use",
        label: `tool · ${event.name}`,
        mono: true,
        text: event.input_preview,
      };
    case "tool_result":
      return {
        bodyClass: `ju-tl-tool_result${event.is_error ? " ju-tl-error" : ""}`,
        label: event.is_error ? "result · error" : "result",
        mono: true,
        text: event.content,
      };
  }
};

/** One timeline event. When `session` is set and the block was clipped, a "show full" control
 *  fetches the untruncated block on demand. */
export function TimelineEventRow({ event, session }: { event: TimelineEvent; session?: string }) {
  const [full, setFull] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const info = display(event);
  const body = full ?? info.text;
  const canExpand = event.ref !== null && session !== undefined && full === null;

  const showFull = () => {
    if (event.ref === null || session === undefined) return;
    setLoading(true);
    fetchBlock(session, event.ref.record_id, event.ref.block_index)
      .then((b) => setFull(b.text))
      .catch(() => setFull(info.text))
      .finally(() => setLoading(false));
  };

  return (
    <div className="ju-tl-event">
      <div className="ju-tl-time">{clock(event.timestamp)}</div>
      <div className={`ju-tl-body ${info.bodyClass}`}>
        <div className="ju-tl-label">{info.label}</div>
        <JsonOrText text={body} mono={info.mono} />
        {canExpand && (
          <button className="ju-tl-more" onClick={showFull} disabled={loading}>
            {loading ? "loading…" : "show full"}
          </button>
        )}
      </div>
    </div>
  );
}

/** Fetches and renders one session's turn-by-turn content within a bucket. */
function SessionTimelineView({
  session,
  grain,
  bucket,
}: {
  session: string;
  grain: string;
  bucket: string;
}) {
  const [timeline, setTimeline] = useState<SessionTimeline | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setTimeline(null);
    setError(null);
    fetchSessionTimeline(session, grain, bucket)
      .then((t) => live && setTimeline(t))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [session, grain, bucket]);

  if (error !== null || timeline === null) {
    return (
      <div className="ju-timeline">
        <div className="ju-muted" style={{ fontSize: 12 }}>
          {error ?? "Loading transcript…"}
        </div>
      </div>
    );
  }
  if (!timeline.events.length) {
    return (
      <div className="ju-timeline">
        <div className="ju-muted" style={{ fontSize: 12 }}>
          No transcript content stored for this session in range.
        </div>
      </div>
    );
  }
  return (
    <div className="ju-timeline">
      {timeline.events.map((event, index) => (
        <TimelineEventRow key={index} event={event} session={session} />
      ))}
      {timeline.truncated && (
        <div className="ju-muted" style={{ fontSize: 12 }}>
          Timeline truncated to the first {timeline.events.length} events.
        </div>
      )}
    </div>
  );
}

const bucketSessionColumns = (navigate: ReturnType<typeof useNavigate>) => {
  const projectColumn = projectLinkColumn<BucketSessionUsage>({
    projectOf: (r) => r.project,
    onClick: (project) => navigate(toProjects(project)),
  });
  return [
    sessionLinkColumn<BucketSessionUsage>({
      idOf: (r) => r.session_id,
      onClick: (r) => navigate(toContextSession(r.session_id)),
      extra: (r) => (r.project ? <div className="ju-muted ju-clip">{projectColumn.render(r)}</div> : null),
    }),
    modelLinkColumn<BucketSessionUsage>({ modelOf: (r) => r.model, onClick: (model) => navigate(toModels(model)) }),
    tokensColumn<BucketSessionUsage>((r) => r.tokens.total_tokens),
    costColumn<BucketSessionUsage>((r) => r.notional_cost_usd),
    turnsColumn<BucketSessionUsage>((r) => r.turns),
  ];
};

/** Fetches and renders a bucket's session breakdown. Empty `bucket` renders a hint. */
export function BucketDetailPanel({
  grain,
  bucket,
  hint,
}: {
  grain: string;
  bucket: string;
  hint: string;
}) {
  const navigate = useNavigate();
  const [detail, setDetail] = useState<BucketDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState("");
  const [page, setPage] = useState(0);

  useEffect(() => {
    if (!bucket) return;
    let live = true;
    setDetail(null);
    setError(null);
    setExpanded("");
    setPage(0);
    fetchBucket(grain, bucket)
      .then((d) => live && setDetail(d))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [grain, bucket]);

  if (!bucket) {
    return (
      <Card>
        <div className="ju-muted" style={{ fontSize: 12 }}>{hint}</div>
      </Card>
    );
  }
  if (error) return <EmptyState>{error}</EmptyState>;

  const metaText = detail
    ? `${fmtTok(detail.tokens.total_tokens)} · ${fmtInt(detail.sessions)} sessions · ${money(detail.notional_cost_usd)}`
    : "Loading sessions";

  return (
    <Card
      title={bucket}
      meta={
        detail ? (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 12 }}>
            <span>{metaText}</span>
            <ExportButtons rows={detail.session_rows} columns={bucketSessionExportColumns} filename={`bucket-${bucket}`} />
          </span>
        ) : (
          metaText
        )
      }
    >
      {detail && (
        <>
          <TokenBuckets tokens={detail.tokens} />
          <div className="ju-muted" style={{ fontSize: 12, marginTop: 12 }}>
            Click a session to expand its turn-by-turn transcript — what was sent and when.
          </div>
          <div style={{ marginTop: 8 }}>
            <DataTable
              rows={detail.session_rows.slice(page * BUCKET_SESSIONS_PAGE_SIZE, (page + 1) * BUCKET_SESSIONS_PAGE_SIZE)}
              rowKey={(r) => r.session_id}
              onRowClick={(r) => setExpanded(expanded === r.session_id ? "" : r.session_id)}
              selectedKey={expanded}
              expandedKey={expanded}
              renderExpanded={(r) => (
                <SessionTimelineView session={r.session_id} grain={grain} bucket={bucket} />
              )}
              columns={bucketSessionColumns(navigate)}
            />
            <Pagination page={page} pageSize={BUCKET_SESSIONS_PAGE_SIZE} total={detail.session_rows.length} onPageChange={setPage} />
          </div>
        </>
      )}
    </Card>
  );
}

export function usageBarChart(data: BarDatum[], onSelect?: (id: string) => void) {
  return data.length ? (
    <BarChart data={data} series={series} onSelect={onSelect} />
  ) : (
    <EmptyState>No usage in range</EmptyState>
  );
}
