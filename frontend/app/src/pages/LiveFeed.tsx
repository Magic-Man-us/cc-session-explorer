import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, EmptyState, Input, JsonOrText, Pagination, Pill, fmtInt, fmtTok } from "@cc-session/dashboard-ui";
import {
  fetchLiveSessions,
  fetchSessionLog,
  type LiveSession,
  type LogBlock,
  type LogRecord,
} from "../api";

const LIST_POLL_MS = 5000;
const FOLLOW_POLL_MS = 3000;
const WINDOW_MIN = 180;
const FRESH_MS = 120_000;
const MAX_ROWS = 2_000; // DOM guard; older rows fall off the top of the follow buffer
const FEED_PAGE_SIZE = 10;

const shortId = (id: string): string => id.slice(0, 8);
const stamp = (ts: string | null): string => (ts ? ts.slice(11, 19) : "—");

const PROSE_BLOCKS = new Set(["text", "thinking"]);

/** Where each tool_use id was called and answered, the answer's own block (so a call can
 *  embed its result inline instead of standing as a separate item), and the tool's name. */
interface ToolLinks {
  callLine: Map<string, number>;
  resultBlock: Map<string, LogBlock>;
  toolName: Map<string, string>;
}

const buildToolLinks = (records: LogRecord[]): ToolLinks => {
  const links: ToolLinks = { callLine: new Map(), resultBlock: new Map(), toolName: new Map() };
  for (const record of records) {
    for (const block of record.blocks) {
      if (!block.tool_use_id) continue;
      if (block.kind === "tool_use") {
        links.callLine.set(block.tool_use_id, record.line);
        if (block.label) links.toolName.set(block.tool_use_id, block.label);
      } else if (block.kind === "tool_result") {
        links.resultBlock.set(block.tool_use_id, block);
      }
    }
  }
  return links;
};

/** True for a tool_result block whose call is known — it renders embedded under that
 *  call instead of standing on its own, so it's dropped everywhere else. */
const isAbsorbed = (block: LogBlock, links: ToolLinks): boolean =>
  block.kind === "tool_result" && block.tool_use_id !== null && links.callLine.has(block.tool_use_id);

function BlockRow({ block, links }: { block: LogBlock; links: ToolLinks }) {
  const mono = !PROSE_BLOCKS.has(block.kind);
  const toolName = block.tool_use_id ? links.toolName.get(block.tool_use_id) : undefined;
  const label =
    block.kind === "tool_result"
      ? `tool_result${toolName ? ` · ${toolName}` : ""}`
      : block.label
        ? `${block.kind} · ${block.label}`
        : block.kind;
  const result = block.kind === "tool_use" && block.tool_use_id ? links.resultBlock.get(block.tool_use_id) : undefined;

  return (
    <div className="ju-tl-block">
      <div className="ju-tl-label">
        {label}
        {block.is_error ? " · error" : ""}
        {block.truncated ? " · truncated" : ""}
      </div>
      <JsonOrText text={block.text} mono={mono} />
      {block.kind === "tool_use" &&
        block.tool_use_id !== null &&
        (result ? (
          <div className={`ju-tl-call-result${result.is_error ? " ju-tl-error" : ""}`}>
            <div className="ju-tl-label">
              → result
              {result.is_error ? " · error" : ""}
              {result.truncated ? " · truncated" : ""}
            </div>
            <JsonOrText text={result.text} />
          </div>
        ) : (
          <div className="ju-tl-pending">→ running…</div>
        ))}
    </div>
  );
}

function DetailList({ details, links }: { details: DetailEntry[]; links: ToolLinks }) {
  if (!details.length) return null;
  return (
    <div className="ju-chat-details">
      {details.map((entry, index) => (
        <BlockRow key={index} block={entry.block} links={links} />
      ))}
    </div>
  );
}

/** One non-chat-text block (thinking, tool_use, tool_result, …) folded into the
 *  detail panel of the message that follows it. */
interface DetailEntry {
  record: LogRecord;
  block: LogBlock;
}

/** A plain-text turn — the thing that actually reads as a message. */
interface FeedMessage {
  type: "message";
  key: string;
  line: number;
  role: "assistant" | "user";
  timestamp: string | null;
  text: string;
  meta: string[];
  details: DetailEntry[];
}

/** A run of tool/thinking activity with no chat text of its own — e.g. a session
 *  that opens with tool calls before its first reply. */
interface FeedActivity {
  type: "activity";
  key: string;
  timestamp: string | null;
  details: DetailEntry[];
}

type FeedItem = FeedMessage | FeedActivity;

const messageMeta = (record: LogRecord): string[] =>
  [record.tokens ? `${fmtTok(record.tokens.total_tokens)} tok` : null, record.is_sidechain ? "sidechain" : null].filter(
    (v): v is string => v !== null,
  );

/** Walks records in order, turning each real text turn into a message and folding
 *  everything else (thinking, tool calls, tool results) into the following message's
 *  detail panel — so a click on a message reveals what led to it. */
function buildFeed(records: LogRecord[], links: ToolLinks): FeedItem[] {
  const items: FeedItem[] = [];
  let buffer: DetailEntry[] = [];
  let activityIndex = 0;

  const flushActivity = () => {
    if (!buffer.length) return;
    const last = buffer[buffer.length - 1];
    items.push({ type: "activity", key: `act-${activityIndex++}`, timestamp: last.record.timestamp, details: buffer });
    buffer = [];
  };

  for (const record of records) {
    for (const block of record.blocks) {
      if (isAbsorbed(block, links)) continue;
      const isChatText = block.kind === "text" && (record.kind === "user" || record.kind === "assistant");
      if (isChatText) {
        const details = buffer;
        buffer = [];
        items.push({
          type: "message",
          key: `msg-${record.line}`,
          line: record.line,
          role: record.kind === "user" ? "user" : "assistant",
          timestamp: record.timestamp,
          text: block.text,
          meta: messageMeta(record),
          details,
        });
      } else {
        buffer.push({ record, block });
      }
    }
  }
  flushActivity();
  return items;
}

const matchesFeedItem = (item: FeedItem, query: string): boolean => {
  if (!query) return true;
  const q = query.toLowerCase();
  if (item.type === "message" && item.text.toLowerCase().includes(q)) return true;
  return item.details.some(
    (d) =>
      d.block.text.toLowerCase().includes(q) ||
      (d.block.label ?? "").toLowerCase().includes(q) ||
      d.block.kind.toLowerCase().includes(q),
  );
};

function FeedRow({
  item,
  expanded,
  onToggle,
  links,
}: {
  item: FeedItem;
  expanded: boolean;
  onToggle: () => void;
  links: ToolLinks;
}) {
  if (item.type === "activity") {
    return (
      <div className="ju-chat-activity">
        <button className="ju-chat-activity-toggle" onClick={onToggle}>
          <span className="ju-chat-icon">⚙</span>
          <span>
            {item.details.length} tool event{item.details.length === 1 ? "" : "s"}
          </span>
          <span className="ju-muted">{stamp(item.timestamp)}</span>
          <span>{expanded ? "▾" : "▸"}</span>
        </button>
        {expanded && <DetailList details={item.details} links={links} />}
      </div>
    );
  }

  const hasDetails = item.details.length > 0;
  return (
    <div className={`ju-chat-row ju-chat-${item.role}`}>
      <div className="ju-chat-avatar">{item.role === "assistant" ? "C" : "U"}</div>
      <div className="ju-chat-col">
        <div className="ju-chat-meta-line">
          <span className="ju-chat-name">{item.role === "assistant" ? "claude" : "user"}</span>
          <span className="ju-muted">{stamp(item.timestamp)}</span>
          {item.meta.length > 0 && <span className="ju-muted">{item.meta.join(" · ")}</span>}
          {hasDetails && (
            <button className="ju-chat-expand" onClick={onToggle}>
              {expanded ? "▾" : "▸"} {item.details.length} tool event{item.details.length === 1 ? "" : "s"}
            </button>
          )}
        </div>
        <div
          className="ju-chat-bubble"
          style={hasDetails ? { cursor: "pointer" } : undefined}
          onClick={hasDetails ? onToggle : undefined}
        >
          <JsonOrText text={item.text} />
        </div>
        {expanded && hasDetails && <DetailList details={item.details} links={links} />}
      </div>
    </div>
  );
}

/** Tails one session's transcript file as a chat-style message feed, newest first. */
function LogFollow({ session, info }: { session: string; info?: LiveSession }) {
  const [records, setRecords] = useState<LogRecord[]>([]);
  const [file, setFile] = useState("");
  const [skipped, setSkipped] = useState(0);
  const [status, setStatus] = useState("Loading");
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [page, setPage] = useState(0);
  const cursorRef = useRef({ offset: 0, line: 0 });

  useEffect(() => {
    let live = true;
    setRecords([]);
    setFile("");
    setSkipped(0);
    setStatus("Loading");
    setExpanded(new Set());
    setPage(0);
    cursorRef.current = { offset: 0, line: 0 };

    const poll = (initial: boolean) =>
      fetchSessionLog(session, cursorRef.current.offset, cursorRef.current.line)
        .then((log) => {
          if (!live) return;
          cursorRef.current = { offset: log.offset, line: log.line };
          setFile(log.file);
          // Skipped lines stay missing from the buffer, so the tally accumulates;
          // a restart replaces the buffer and the count starts over.
          setSkipped((prev) => (log.restarted ? log.skipped : prev + log.skipped));
          setStatus("Following · " + new Date().toISOString().slice(11, 19));
          if (!log.records.length && !log.restarted) {
            if (initial) setStatus("Waiting for the first record");
            return;
          }
          setRecords((prev) => (log.restarted ? log.records : [...prev, ...log.records]).slice(-MAX_ROWS));
        })
        .catch((e: Error) => live && setStatus(e.message));

    poll(true);
    const timer = setInterval(() => poll(false), FOLLOW_POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
  }, [session]);

  const links = useMemo(() => buildToolLinks(records), [records]);
  const feed = useMemo(() => buildFeed(records, links), [records, links]);

  const totals = useMemo(() => {
    let output = 0;
    let toolCalls = 0;
    for (const record of records) {
      output += record.tokens?.output_tokens ?? 0;
      toolCalls += record.blocks.filter((b) => b.kind === "tool_use").length;
    }
    return { output, toolCalls };
  }, [records]);

  const filtered = useMemo(() => feed.filter((item) => matchesFeedItem(item, query)), [feed, query]);
  const newestFirst = useMemo(() => [...filtered].reverse(), [filtered]);
  const pageItems = newestFirst.slice(page * FEED_PAGE_SIZE, (page + 1) * FEED_PAGE_SIZE);

  const toggle = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const headline = info?.project || info?.first_prompt || "";

  return (
    <Card title={shortId(session)} meta={`${file || "…"} · ${fmtInt(records.length)} records · ${status}`}>
      {headline && (
        <div className="ju-muted" style={{ fontSize: 12, marginBottom: 8 }}>
          {headline}
          {info?.turns ? ` · ${fmtInt(info.turns)} turns` : ""}
          {` · ${fmtTok(totals.output)} output tok · ${fmtInt(totals.toolCalls)} tool calls`}
        </div>
      )}
      <Input
        style={{ marginBottom: 10 }}
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setPage(0);
        }}
        placeholder="filter messages — text, tool name…"
      />
      {skipped > 0 && (
        <div className="ju-muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Showing the newest records; {fmtInt(skipped)} earlier lines fell outside the buffer.
        </div>
      )}
      <div className="ju-chat-feed">
        {pageItems.length ? (
          pageItems.map((item) => (
            <FeedRow key={item.key} item={item} expanded={expanded.has(item.key)} onToggle={() => toggle(item.key)} links={links} />
          ))
        ) : (
          <div className="ju-muted" style={{ fontSize: 12 }}>
            {feed.length ? "No messages match the current filter." : status}
          </div>
        )}
      </div>
      <Pagination page={page} pageSize={FEED_PAGE_SIZE} total={filtered.length} onPageChange={setPage} />
    </Card>
  );
}

export function LiveFeed() {
  const [selected, setSelected] = useState("");
  const [manual, setManual] = useState("");
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["live", "sessions"],
    queryFn: () => fetchLiveSessions(WINDOW_MIN),
    refetchInterval: LIST_POLL_MS,
  });
  const sessions: LiveSession[] = data?.sessions ?? [];
  const status = isPending
    ? "Waiting"
    : isError
      ? error.message
      : `${sessions.length} active · ${data?.generated_at.slice(11, 19) ?? ""}`;

  const now = Date.now();

  return (
    <div style={{ display: "grid", gap: 14, gridTemplateColumns: "minmax(280px, 360px) 1fr" }}>
      <Card title="live sessions" meta={status}>
        <div className="ju-muted" style={{ fontSize: 12, marginBottom: 8 }}>
          Active in the last {WINDOW_MIN} minutes. Click one to watch its live message feed — click
          any message to see the tool calls and thinking behind it.
        </div>
        {sessions.length ? (
          <div style={{ display: "grid", gap: 4 }}>
            {sessions.map((s) => {
              const seen = s.last_seen_at ? new Date(s.last_seen_at).getTime() : 0;
              const fresh = now - seen < FRESH_MS;
              const active = s.session_id === selected;
              return (
                <button
                  key={s.session_id}
                  className={`ju-session-row${active ? " ju-active" : ""}`}
                  onClick={() => setSelected(s.session_id)}
                >
                  <span className={`ju-dot ${fresh ? "ju-fresh" : "ju-stale"}`} />
                  <span className="ju-session-main">
                    <span className="ju-mono">{shortId(s.session_id)}</span>
                    <span className="ju-muted ju-clip">{s.project || s.first_prompt || ""}</span>
                  </span>
                  <span className="ju-session-meta">
                    <span>{fmtInt(s.turns)} turns</span>
                    <span className="ju-muted">{stamp(s.last_seen_at)}</span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="ju-muted" style={{ fontSize: 12 }}>
            No sessions active in the window. <Pill>idle</Pill>
          </div>
        )}
        <form
          style={{ display: "flex", gap: 6, marginTop: 10 }}
          onSubmit={(e) => {
            e.preventDefault();
            if (manual.trim()) setSelected(manual.trim());
          }}
        >
          <Input value={manual} onChange={(e) => setManual(e.target.value)} placeholder="or paste any session id" />
        </form>
      </Card>

      {selected ? (
        <LogFollow session={selected} info={sessions.find((s) => s.session_id === selected)} />
      ) : (
        <EmptyState>Select a session to watch its live message feed.</EmptyState>
      )}
    </div>
  );
}
