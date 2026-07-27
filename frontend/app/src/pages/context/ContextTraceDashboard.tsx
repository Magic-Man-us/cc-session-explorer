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
const HEIGHT = 300;
const PAD_LEFT = 64;
const PAD_RIGHT = 24;
const PAD_TOP = 30;
const PAD_BOTTOM = 42;
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
  time: number;
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

const niceCeiling = (value: number): number => {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step =
    normalized <= 1 ? 1 :
    normalized <= 2 ? 2 :
    normalized <= 5 ? 5 :
    10;
  return step * magnitude;
};

const traceYMax = (trace: ContextTrace): number =>
  niceCeiling(Math.max(trace.window_tokens, trace.peak_tokens, 1));

const normalizedEventTimes = (
  events: ReadonlyArray<ContextTraceEvent>,
): number[] => {
  const parsed = events.map((event) => parseMillis(event.timestamp));
  const firstKnown = parsed.find((value): value is number => value !== null);
  if (firstKnown === undefined) return events.map((_, index) => index);

  let previous = firstKnown;
  return parsed.map((value) => {
    const resolved = value === null ? previous : Math.max(previous, value);
    previous = resolved;
    return resolved;
  });
};

const positionEvents = (trace: ContextTrace): PositionedEvent[] => {
  if (trace.events.length === 0) return [];
  const timestamps = normalizedEventTimes(trace.events);
  const start = timestamps[0];
  const end = timestamps[timestamps.length - 1];
  const timeSpan = end - start;
  const chartWidth = WIDTH - PAD_LEFT - PAD_RIGHT;
  const chartHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const yMax = traceYMax(trace);

  return trace.events.map((event, index) => {
    const time = timestamps[index];
    const ratio =
      timeSpan > 0
        ? (time - start) / timeSpan
        : trace.events.length === 1
          ? 0.5
          : index / (trace.events.length - 1);
    const yFor = (tokens: number) =>
      PAD_TOP + chartHeight * (1 - Math.min(Math.max(tokens, 0) / yMax, 1));
    return {
      event,
      time,
      x: PAD_LEFT + ratio * chartWidth,
      y: yFor(event.context_after_tokens),
      yBefore: yFor(event.context_before_tokens),
    };
  });
};

const collapseLinePoints = (
  points: ReadonlyArray<PositionedEvent>,
): PositionedEvent[] => {
  const collapsed: PositionedEvent[] = [];
  for (const point of points) {
    const previous = collapsed[collapsed.length - 1];
    if (previous !== undefined && Math.round(previous.x) === Math.round(point.x)) {
      collapsed[collapsed.length - 1] = point;
    } else {
      collapsed.push(point);
    }
  }
  return collapsed;
};

const stepPath = (points: ReadonlyArray<PositionedEvent>): string => {
  if (points.length === 0) return "";
  return points.slice(1).reduce(
    (path, point) => `${path} H ${point.x} V ${point.y}`,
    `M ${points[0].x} ${points[0].y}`,
  );
};

const uniqueMarkers = (
  points: ReadonlyArray<PositionedEvent>,
): PositionedEvent[] => {
  const markers = new Map<string, PositionedEvent>();
  for (const point of points) {
    if (point.event.kind !== "compaction" && point.event.kind !== "subagent") {
      continue;
    }
    markers.set(`${point.event.kind}:${Math.round(point.x)}`, point);
  }
  return [...markers.values()];
};

function TraceInspector({
  point,
  windowTokens,
}: {
  point: PositionedEvent | null;
  windowTokens: number;
}) {
  if (point === null) {
    return (
      <div className="cc-trace-inspector cc-trace-inspector-empty">
        Hover the chart to inspect activity. Click a point to open its
        surrounding 30-minute window.
      </div>
    );
  }
  const { event } = point;
  const utilization =
    windowTokens > 0
      ? Math.round((event.context_after_tokens / windowTokens) * 100)
      : null;
  return (
    <div
      className="cc-trace-inspector"
      role="status"
    >
      <span
        className="cc-trace-inspector-kind"
        style={{ color: EVENT_COLORS[event.kind] }}
      >
        {EVENT_LABELS[event.kind]}
      </span>
      <time>{fmtTime(event.timestamp)}</time>
      <strong title={event.label}>{event.label}</strong>
      <span className="cc-trace-inspector-context">
        {fmtTok(event.context_after_tokens)} active
        {utilization !== null && ` · ${utilization}%`}
        <small>{fmtDelta(event.token_delta)} · {event.measurement}</small>
      </span>
    </div>
  );
}

export function ContextLineGraph({
  trace,
  selectedSequence,
  onSelect,
}: {
  trace: ContextTrace;
  selectedSequence: number | null;
  onSelect: (event: ContextTraceEvent) => void;
}) {
  const points = useMemo(() => positionEvents(trace), [trace]);
  const linePoints = useMemo(() => collapseLinePoints(points), [points]);
  const markers = useMemo(() => uniqueMarkers(points), [points]);
  const [hoveredSequence, setHoveredSequence] = useState<number | null>(null);
  const hovered =
    points.find((point) => point.event.sequence === hoveredSequence) ?? null;
  const selected =
    points.find((point) => point.event.sequence === selectedSequence) ?? null;
  const inspected = hovered ?? selected;
  const line = stepPath(linePoints);
  const yMax = traceYMax(trace);
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
    fraction,
    tokens: fraction * yMax,
  }));
  const hasRecordedTime = trace.events.some(
    (event) => parseMillis(event.timestamp) !== null,
  );
  const startTime = hasRecordedTime ? points[0]?.time ?? null : null;
  const endTime = hasRecordedTime ? points[points.length - 1]?.time ?? null : null;
  const xTicks =
    startTime !== null && endTime !== null
      ? (startTime === endTime ? [0.5] : [0, 0.5, 1]).map((fraction) => ({
          fraction,
          label: fmtAxisTime(
            startTime + (endTime - startTime) * fraction,
            new Date(startTime).toDateString() !== new Date(endTime).toDateString(),
          ),
        }))
      : [0, 0.5, 1].map((fraction) => ({
          fraction,
          label: fraction === 0 ? "start" : fraction === 1 ? "end" : "middle",
        }));
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
    <div className="cc-trace-chart-shell">
      <div className="cc-trace-chart-scroll">
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

          {yTicks.map(({ fraction, tokens }) => {
            const y =
              PAD_TOP +
              (HEIGHT - PAD_TOP - PAD_BOTTOM) * (1 - fraction);
            return (
              <g key={fraction}>
                <line
                  x1={PAD_LEFT}
                  x2={WIDTH - PAD_RIGHT}
                  y1={y}
                  y2={y}
                  className="cc-trace-grid"
                />
                <text
                  x={PAD_LEFT - 9}
                  y={y + 4}
                  className="cc-trace-axis-label"
                  textAnchor="end"
                >
                  {fmtTok(tokens)}
                </text>
              </g>
            );
          })}

          {trace.window_tokens > 0 && trace.window_tokens < yMax && (
            <g>
              <line
                x1={PAD_LEFT}
                x2={WIDTH - PAD_RIGHT}
                y1={PAD_TOP + (HEIGHT - PAD_TOP - PAD_BOTTOM) * (1 - trace.window_tokens / yMax)}
                y2={PAD_TOP + (HEIGHT - PAD_TOP - PAD_BOTTOM) * (1 - trace.window_tokens / yMax)}
                className="cc-trace-window-limit"
              />
            </g>
          )}

          <line
            x1={PAD_LEFT}
            x2={WIDTH - PAD_RIGHT}
            y1={PAD_TOP}
            y2={PAD_TOP}
            className="cc-trace-event-rail"
          />

          {line && <path d={line} className="cc-trace-line" />}

          {markers.map((point) =>
            point.event.kind === "compaction" ? (
              <g key={`compaction-${point.event.sequence}`}>
                <line
                  x1={point.x}
                  x2={point.x}
                  y1={point.yBefore}
                  y2={point.y}
                  className="cc-trace-compaction-drop"
                />
                <circle
                  cx={point.x}
                  cy={point.y}
                  r={5}
                  className="cc-trace-compaction-dot"
                />
              </g>
            ) : (
              <path
                key={`subagent-${point.event.sequence}`}
                d={`M ${point.x} ${PAD_TOP + 2} l -5 -9 h 10 Z`}
                className="cc-trace-subagent-marker"
              />
            ),
          )}

          {selected && (
            <>
              <line
                x1={selected.x}
                x2={selected.x}
                y1={PAD_TOP}
                y2={HEIGHT - PAD_BOTTOM}
                className="cc-trace-selection"
              />
              <circle
                cx={selected.x}
                cy={selected.y}
                r={4}
                className="cc-trace-selection-dot"
              />
            </>
          )}
          {hovered && (
            <>
              <line
                x1={hovered.x}
                x2={hovered.x}
                y1={PAD_TOP}
                y2={HEIGHT - PAD_BOTTOM}
                className="cc-trace-cursor"
              />
              <circle
                cx={hovered.x}
                cy={hovered.y}
                r={4}
                className="cc-trace-cursor-dot"
              />
            </>
          )}

          {xTicks.map(({ fraction, label }) => (
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
                y={HEIGHT - PAD_BOTTOM + 18}
                className="cc-trace-axis-label"
                textAnchor={fraction === 0 ? "start" : fraction === 1 ? "end" : "middle"}
              >
                {label}
              </text>
            </g>
          ))}
          <text
            x={PAD_LEFT}
            y={14}
            className="cc-trace-axis-title"
          >
            Active context · tokens
          </text>
          {trace.window_tokens > 0 && (
            <text
              x={WIDTH - PAD_RIGHT}
              y={14}
              className="cc-trace-limit-label"
              textAnchor="end"
            >
              context limit · {fmtTok(trace.window_tokens)}
            </text>
          )}
          <text
            x={(PAD_LEFT + WIDTH - PAD_RIGHT) / 2}
            y={HEIGHT - 4}
            className="cc-trace-axis-title"
            textAnchor="middle"
          >
            {hasRecordedTime ? "Session time" : "Event order"}
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
            onClick={click}
          />
        </svg>
      </div>
      <TraceInspector point={inspected} windowTokens={trace.window_tokens} />
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
