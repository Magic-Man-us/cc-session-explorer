import {
  useEffect,
  useMemo,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Card,
  EmptyState,
  KpiCard,
  LoadingState,
  fmtTok,
} from "@cc-session/dashboard-ui";

import type {
  ContextTrace,
  ContextTraceEvent,
  TraceEventKind,
} from "../../api";
import { useProviderScope } from "../../provider";
import {
  contextTraceOptions,
  contextTraceWindowOptions,
} from "./traceQueries";

const WIDTH = 1_200;
const HEIGHT = 350;
const PAD_LEFT = 92;
const PAD_RIGHT = 28;
const PAD_TOP = 24;
const PAD_BOTTOM = 58;
const SELECTION_MINUTES = 30;

const EVENT_LABELS: Record<TraceEventKind, string> = {
  context_load: "context loaded",
  prompt: "prompt",
  thinking: "thinking",
  response: "response",
  tool_call: "tool call",
  tool_result: "tool result",
  hook: "hook",
  subagent: "subagent",
  compaction: "compaction",
  system: "system",
  error: "error",
};

const EVENT_COLORS: Record<TraceEventKind, string> = {
  context_load: "var(--blue)",
  prompt: "var(--green)",
  thinking: "var(--violet)",
  response: "var(--green)",
  tool_call: "var(--amber)",
  tool_result: "var(--muted)",
  hook: "var(--amber)",
  subagent: "var(--violet)",
  compaction: "var(--red)",
  system: "var(--muted)",
  error: "var(--red)",
};

interface PositionedEvent {
  event: ContextTraceEvent;
  x: number;
  y: number;
  yBefore: number;
}

const parseMillis = (timestamp: string | null): number | null => {
  if (timestamp === null) return null;
  const value = Date.parse(timestamp);
  return Number.isNaN(value) ? null : value;
};

const fmtTime = (timestamp: string | null): string => {
  if (timestamp === null) return "time unavailable";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "time unavailable";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const fmtClock = (timestamp: string | null): string => {
  if (timestamp === null) return "—";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
};

const fmtAxisTime = (timestamp: number, showDate: boolean): string =>
  new Date(timestamp).toLocaleString([], showDate
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }
    : { hour: "2-digit", minute: "2-digit" });

const fmtDelta = (tokens: number): string => {
  if (tokens === 0) return "no measured context change";
  return `${tokens > 0 ? "+" : "−"}${fmtTok(Math.abs(tokens))}`;
};

const fmtDuration = (durationMs: number | null): string | null => {
  if (durationMs === null) return null;
  if (durationMs < 1_000) return `${durationMs} ms`;
  return `${(durationMs / 1_000).toFixed(1)} s`;
};

const positionEvents = (trace: ContextTrace): PositionedEvent[] => {
  if (trace.events.length === 0) return [];
  const timestamps = trace.events.map((event) => parseMillis(event.timestamp));
  const dated = timestamps.filter((value): value is number => value !== null);
  const start = dated.length > 0 ? Math.min(...dated) : 0;
  const end = dated.length > 0 ? Math.max(...dated) : 0;
  const timeSpan = end - start;
  const chartWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const chartHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const yMax = Math.max(trace.window_tokens, trace.peak_tokens, 1);

  return trace.events.map((event, index) => {
    const time = timestamps[index];
    const ratio =
      time !== null && timeSpan > 0
        ? (time - start) / timeSpan
        : trace.events.length === 1
          ? 0.5
          : index / (trace.events.length - 1);
    const yFor = (tokens: number) =>
      PAD_TOP + chartHeight * (1 - Math.min(tokens / yMax, 1));
    return {
      event,
      x: PAD_LEFT + ratio * chartWidth,
      y: yFor(event.context_after_tokens),
      yBefore: yFor(event.context_before_tokens),
    };
  });
};

function TraceTooltip({ point }: { point: PositionedEvent }) {
  const { event } = point;
  return (
    <div
      className={`cc-trace-tooltip${point.y < 100 ? " cc-trace-tooltip-below" : ""}`}
      style={{
        left: `clamp(155px, ${(point.x / WIDTH) * 100}%, calc(100% - 155px))`,
        top: `${Math.max((point.y / HEIGHT) * 100, 6)}%`,
      }}
      role="status"
    >
      <div className="cc-trace-tooltip-head">
        <span style={{ color: EVENT_COLORS[event.kind] }}>
          {EVENT_LABELS[event.kind]}
        </span>
        <span>{fmtClock(event.timestamp)}</span>
      </div>
      <strong>{event.label}</strong>
      <div>
        {fmtTok(event.context_after_tokens)} active ·{" "}
        {fmtDelta(event.token_delta)}
      </div>
      <div className="cc-trace-confidence">{event.measurement}</div>
    </div>
  );
}

function ContextLineGraph({
  trace,
  selectedSequence,
  onSelect,
}: {
  trace: ContextTrace;
  selectedSequence: number | null;
  onSelect: (event: ContextTraceEvent) => void;
}) {
  const points = useMemo(() => positionEvents(trace), [trace]);
  const [hoveredSequence, setHoveredSequence] = useState<number | null>(null);
  const hovered =
    points.find((point) => point.event.sequence === hoveredSequence) ?? null;
  const selected =
    points.find((point) => point.event.sequence === selectedSequence) ?? null;
  const inspected = hovered ?? selected;
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area =
    points.length > 0
      ? `M ${points[0].x} ${HEIGHT - PAD_BOTTOM} L ${points
          .map((point) => `${point.x} ${point.y}`)
          .join(" L ")} L ${points[points.length - 1].x} ${HEIGHT - PAD_BOTTOM} Z`
      : "";
  const yMax = Math.max(trace.window_tokens, trace.peak_tokens, 1);
  const windowGrid = trace.window_tokens > 0
    ? [0, 0.5, 0.8, 1].map((fraction) => ({
        fraction,
        tokens: fraction * trace.window_tokens,
      }))
    : [0, 0.5, 1].map((fraction) => ({
        fraction: null,
        tokens: fraction * yMax,
      }));
  const yTicks = [
    ...windowGrid,
    ...(trace.peak_tokens > trace.window_tokens
      ? [{ fraction: null, tokens: trace.peak_tokens }]
      : []),
  ].filter(
    (tick, index, ticks) =>
      ticks.findIndex((candidate) => candidate.tokens === tick.tokens) === index,
  );
  const datedPoints = points
    .map((point) => parseMillis(point.event.timestamp))
    .filter((timestamp): timestamp is number => timestamp !== null);
  const startTime = parseMillis(trace.started_at) ??
    (datedPoints.length > 0 ? Math.min(...datedPoints) : null);
  const endTime = parseMillis(trace.ended_at) ??
    (datedPoints.length > 0 ? Math.max(...datedPoints) : null);
  const xTicks =
    startTime !== null && endTime !== null
      ? [0, 0.5, 1].map((fraction) => ({
          fraction,
          timestamp: startTime + (endTime - startTime) * fraction,
        }))
      : [];
  const showDate =
    startTime !== null &&
    endTime !== null &&
    new Date(startTime).toDateString() !== new Date(endTime).toDateString();

  const nearestAt = (clientX: number, target: SVGRectElement) => {
    const svg = target.ownerSVGElement;
    if (svg === null || points.length === 0) return null;
    const bounds = svg.getBoundingClientRect();
    const x = ((clientX - bounds.left) / bounds.width) * WIDTH;
    return points.reduce((nearest, point) =>
      Math.abs(point.x - x) < Math.abs(nearest.x - x) ? point : nearest,
    );
  };

  const move = (event: ReactPointerEvent<SVGRectElement>) => {
    const nearest = nearestAt(event.clientX, event.currentTarget);
    setHoveredSequence(nearest?.event.sequence ?? null);
  };

  const click = (event: ReactPointerEvent<SVGRectElement>) => {
    const nearest = nearestAt(event.clientX, event.currentTarget);
    if (nearest !== null) onSelect(nearest.event);
  };

  const keyDown = (event: ReactKeyboardEvent<SVGSVGElement>) => {
    if (points.length === 0) return;
    const current = hoveredSequence ?? selectedSequence ?? points[0].event.sequence;
    const currentIndex = Math.max(
      points.findIndex((point) => point.event.sequence === current),
      0,
    );
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      const direction = event.key === "ArrowLeft" ? -1 : 1;
      const nextIndex = Math.min(
        Math.max(currentIndex + direction, 0),
        points.length - 1,
      );
      setHoveredSequence(points[nextIndex].event.sequence);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(points[currentIndex].event);
    }
  };

  return (
    <div className="cc-trace-chart-wrap">
      <svg
        className="cc-trace-chart"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-labelledby="context-trace-title context-trace-description"
        tabIndex={0}
        onKeyDown={keyDown}
      >
        <title id="context-trace-title">Active context over the session</title>
        <desc id="context-trace-description">
          Active context tokens plotted against session time. Use the pointer
          to inspect the nearest activity. Click, or use arrow keys and Enter,
          to select a thirty-minute activity window.
        </desc>
        <defs>
          <linearGradient id="cc-trace-area" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="#5eb6f2" stopOpacity="0.32" />
            <stop offset="100%" stopColor="#5eb6f2" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        <text x={PAD_LEFT} y={14} className="cc-trace-axis-title">
          Active context · tokens and context-window utilization
        </text>

        {yTicks.map(({ fraction, tokens }) => {
          const y =
            PAD_TOP +
            (HEIGHT - PAD_TOP - PAD_BOTTOM) * (1 - tokens / yMax);
          return (
            <g key={`${fraction ?? "peak"}-${tokens}`}>
              <line
                x1={PAD_LEFT}
                x2={WIDTH - PAD_RIGHT}
                y1={y}
                y2={y}
                className={`cc-trace-grid${fraction === 0.8 ? " cc-trace-grid-warning" : ""}`}
              />
              <text x={PAD_LEFT - 8} y={y + 4} className="cc-trace-axis-label" textAnchor="end">
                {fraction === null
                  ? fmtTok(tokens)
                  : `${Math.round(fraction * 100)}% · ${fmtTok(tokens)}`}
              </text>
            </g>
          );
        })}

        {area && <path d={area} fill="url(#cc-trace-area)" />}
        {line && <polyline points={line} className="cc-trace-line" />}

        {points.map((point) => {
          const isCompaction = point.event.kind === "compaction";
          const isSubagent = point.event.kind === "subagent";
          if (!isCompaction && !isSubagent) return null;
          return (
            <g key={point.event.sequence}>
              <line
                x1={point.x}
                x2={point.x}
                y1={isCompaction ? point.yBefore : PAD_TOP}
                y2={isCompaction ? point.y : HEIGHT - PAD_BOTTOM}
                className={`cc-trace-marker-line cc-trace-marker-${point.event.kind}`}
              />
              <circle
                cx={point.x}
                cy={point.y}
                r={isCompaction ? 6 : 5}
                fill={EVENT_COLORS[point.event.kind]}
                className="cc-trace-marker-dot"
              />
            </g>
          );
        })}

        {selected && (
          <line
            x1={selected.x}
            x2={selected.x}
            y1={PAD_TOP}
            y2={HEIGHT - PAD_BOTTOM}
            className="cc-trace-selection"
          />
        )}

        {xTicks.map(({ fraction, timestamp }) => (
          <g key={fraction}>
            <line
              x1={PAD_LEFT + fraction * (WIDTH - PAD_LEFT - PAD_RIGHT)}
              x2={PAD_LEFT + fraction * (WIDTH - PAD_LEFT - PAD_RIGHT)}
              y1={HEIGHT - PAD_BOTTOM}
              y2={HEIGHT - PAD_BOTTOM + 5}
              className="cc-trace-axis-tick"
            />
            <text
              x={PAD_LEFT + fraction * (WIDTH - PAD_LEFT - PAD_RIGHT)}
              y={HEIGHT - PAD_BOTTOM + 19}
              className="cc-trace-axis-label"
              textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"}
            >
              {fmtAxisTime(timestamp, showDate)}
            </text>
          </g>
        ))}
        <text
          x={(PAD_LEFT + WIDTH - PAD_RIGHT) / 2}
          y={HEIGHT - 5}
          className="cc-trace-axis-title"
          textAnchor="middle"
        >
          Session time
        </text>

        <rect
          x={PAD_LEFT}
          y={PAD_TOP}
          width={WIDTH - PAD_LEFT - PAD_RIGHT}
          height={HEIGHT - PAD_TOP - PAD_BOTTOM}
          fill="transparent"
          className="cc-trace-hit"
          onPointerMove={move}
          onPointerLeave={() => setHoveredSequence(null)}
          onPointerDown={click}
        />
      </svg>
      {inspected && <TraceTooltip point={inspected} />}
    </div>
  );
}

function CompactionDetails({ event }: { event: ContextTraceEvent }) {
  const compaction = event.compaction;
  if (compaction === null) return null;
  const duration = fmtDuration(compaction.duration_ms);
  const items = [
    compaction.pre_tokens !== null
      ? `before ${fmtTok(compaction.pre_tokens)}`
      : null,
    compaction.post_tokens !== null
      ? `after ${fmtTok(compaction.post_tokens)}`
      : null,
    compaction.dropped_tokens !== null
      ? `removed ${fmtTok(compaction.dropped_tokens)}`
      : null,
    compaction.messages_summarized !== null
      ? `${compaction.messages_summarized} messages summarized`
      : null,
    compaction.preserved_items !== null
      ? `${compaction.preserved_items} items preserved`
      : null,
    duration,
  ].filter((item): item is string => item !== null);
  if (items.length === 0) return null;
  return <div className="cc-trace-compaction-detail">{items.join(" · ")}</div>;
}

function ActivityWindow({
  session,
  selected,
  onSelect,
}: {
  session: string;
  selected: ContextTraceEvent | null;
  onSelect: (event: ContextTraceEvent) => void;
}) {
  const provider = useProviderScope();
  const center = selected?.timestamp ?? null;
  const { data, isPending, isError, error } = useQuery(
    contextTraceWindowOptions(
      session,
      center,
      provider,
      SELECTION_MINUTES,
    ),
  );

  if (selected === null) {
    return (
      <Card title="30-minute activity window" meta="15 minutes before · 15 minutes after">
        <EmptyState>
          Select any point on the context line to inspect every recorded call and
          lifecycle event around it.
        </EmptyState>
      </Card>
    );
  }
  if (center === null) {
    return (
      <Card title="30-minute activity window">
        <EmptyState>
          This event has no recorded timestamp, so a time window cannot be
          centered on it.
        </EmptyState>
      </Card>
    );
  }
  if (isError) {
    return (
      <Card title="30-minute activity window">
        <EmptyState>{error.message}</EmptyState>
      </Card>
    );
  }
  if (isPending || data === undefined) {
    return (
      <Card title="30-minute activity window">
        <LoadingState>Capturing surrounding activity…</LoadingState>
      </Card>
    );
  }

  return (
    <Card
      title="30-minute activity window"
      meta={`${fmtClock(data.starts_at)} – ${fmtClock(data.ends_at)} · ${data.events.length} events`}
    >
      <div className="cc-trace-window-summary">
        <span>Centered on</span>
        <strong>{selected.label}</strong>
        <span>{fmtTime(selected.timestamp)}</span>
      </div>
      {data.events.length === 0 ? (
        <EmptyState>No timestamped activity was recorded in this window.</EmptyState>
      ) : (
        <ol className="cc-trace-activity-list">
          {data.events.map((event) => (
            <li key={event.sequence}>
              <button
                type="button"
                className={`cc-trace-activity${event.sequence === selected.sequence ? " cc-trace-activity-selected" : ""}`}
                onClick={() => onSelect(event)}
              >
                <span className="cc-trace-activity-time">
                  {fmtClock(event.timestamp)}
                </span>
                <span
                  className="cc-trace-activity-kind"
                  style={{ color: EVENT_COLORS[event.kind] }}
                >
                  {EVENT_LABELS[event.kind]}
                </span>
                <span className="cc-trace-activity-main">
                  <strong>{event.label}</strong>
                  {event.detail && <span>{event.detail}</span>}
                  <CompactionDetails event={event} />
                </span>
                <span className="cc-trace-activity-context">
                  {fmtTok(event.context_after_tokens)}
                  <small>{fmtDelta(event.token_delta)}</small>
                </span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function TraceHeading({ provider }: { provider: string }) {
  return (
    <div className="cc-trace-heading">
      <div>
        <h2 id="context-activity-heading">Context activity</h2>
        <p>
          Active context reconstructed from the transcript. Hover to inspect;
          select a point to capture 15 minutes before and after it.
        </p>
      </div>
      <span className="cc-trace-provider">{provider}</span>
    </div>
  );
}

export function ContextTraceDashboard({ session }: { session: string }) {
  const provider = useProviderScope();
  const { data, isPending, isError, error } = useQuery(
    contextTraceOptions(session, provider),
  );
  const [selectedSequence, setSelectedSequence] = useState<number | null>(null);

  useEffect(() => {
    setSelectedSequence(null);
  }, [session, provider]);

  if (isError) {
    return (
      <section className="cc-trace-dashboard" aria-labelledby="context-activity-heading">
        <TraceHeading provider={provider} />
        <Card title="Context growth timeline">
          <EmptyState>{error.message}</EmptyState>
        </Card>
      </section>
    );
  }
  if (isPending || data === undefined) {
    return (
      <section className="cc-trace-dashboard" aria-labelledby="context-activity-heading">
        <TraceHeading provider={provider} />
        <Card title="Context growth timeline">
          <LoadingState>Reconstructing context activity…</LoadingState>
        </Card>
      </section>
    );
  }
  if (data.events.length === 0) {
    return (
      <section className="cc-trace-dashboard" aria-labelledby="context-activity-heading">
        <TraceHeading provider={data.provider} />
        <Card title="Context growth timeline">
          <EmptyState>No traceable context events were captured for this session.</EmptyState>
        </Card>
      </section>
    );
  }

  const selected =
    data.events.find((event) => event.sequence === selectedSequence) ?? null;
  const utilization =
    data.window_tokens > 0
      ? Math.round((data.peak_tokens / data.window_tokens) * 100)
      : 0;
  const select = (event: ContextTraceEvent) =>
    setSelectedSequence(event.sequence);

  return (
    <section className="cc-trace-dashboard" aria-labelledby="context-activity-heading">
      <TraceHeading provider={data.provider} />

      <div className="cc-trace-kpis">
        <KpiCard
          label="Current context"
          value={fmtTok(data.final_tokens)}
          hint={`${data.events.length} traced events`}
        />
        <KpiCard
          label="Peak context"
          value={fmtTok(data.peak_tokens)}
          hint={`${utilization}% of ${fmtTok(data.window_tokens)}`}
        />
        <KpiCard
          label="Compactions"
          value={data.compaction_count}
          hint="before → after markers"
        />
        <KpiCard
          label="Subagent activity"
          value={data.subagent_count}
          hint="spawn and lifecycle markers"
        />
      </div>

      <Card
        title="Context growth timeline"
        meta={`${fmtTime(data.started_at)} – ${fmtTime(data.ended_at)}`}
        className="cc-trace-graph-card"
      >
        <ContextLineGraph
          trace={data}
          selectedSequence={selectedSequence}
          onSelect={select}
        />
        <div className="cc-trace-legend" aria-label="Timeline marker legend">
          <span><i className="cc-trace-legend-line" />active context</span>
          <span><i className="cc-trace-legend-compact" />compaction</span>
          <span><i className="cc-trace-legend-subagent" />subagent</span>
          <span>counts marked exact, estimated, or inferred</span>
        </div>
      </Card>

      <ActivityWindow
        session={session}
        selected={selected}
        onSelect={select}
      />
    </section>
  );
}
