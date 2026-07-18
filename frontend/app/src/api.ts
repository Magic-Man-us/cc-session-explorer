import type { TokenBreakdown } from "@cc-session/dashboard-ui";

// Types mirror the backend's Pydantic payloads (src/cc_session_explorer/usage/models.py).
// TokenBreakdown is reused from the design system so the shape stays shared.

export interface DashboardTotals {
  tokens: TokenBreakdown;
  raw_tokens: TokenBreakdown;
  sessions: number;
  turns: number;
  raw_usage_rows: number;
  duplicate_usage_rows: number;
  notional_cost_usd: number;
}

export interface RecentSession {
  id: string;
  started_at: string | null;
  last_seen_at: string | null;
  first_prompt: string | null;
  project: string | null;
  model: string | null;
  tokens: TokenBreakdown;
  turns: number;
  notional_cost_usd: number;
}

export interface ModelUsage {
  model: string;
  tokens: TokenBreakdown;
  turns: number;
  sessions: number;
  notional_cost_usd: number;
}

export interface ProjectUsage {
  project: string;
  tokens: TokenBreakdown;
  turns: number;
  sessions: number;
  notional_cost_usd: number;
}

export interface DailyUsage {
  day: string;
  tokens: TokenBreakdown;
  turns: number;
  sessions: number;
  notional_cost_usd: number;
}

export interface TimeUsage {
  bucket: string;
  tokens: TokenBreakdown;
  turns: number;
  sessions: number;
  notional_cost_usd: number;
}

export interface UsageEvent {
  key: string;
  timestamp: string | null;
  session_id: string | null;
  project: string | null;
  model: string | null;
  source_kind: string;
  tokens: TokenBreakdown;
  notional_cost_usd: number;
}

export interface UsageTail {
  generated_at: string;
  total_cost_usd: number;
  events: UsageEvent[];
}

export interface BucketSessionUsage {
  session_id: string;
  project: string | null;
  model: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  tokens: TokenBreakdown;
  turns: number;
  notional_cost_usd: number;
}

export interface BucketDetail {
  grain: string;
  bucket: string;
  tokens: TokenBreakdown;
  turns: number;
  sessions: number;
  notional_cost_usd: number;
  session_rows: BucketSessionUsage[];
}

export interface BlockRef {
  record_id: number;
  block_index: number;
}

export interface TimelineTextEvent {
  kind: "text";
  role: "user" | "assistant";
  timestamp: string | null;
  text: string;
  ref: BlockRef | null;
}

export interface TimelineThinkingEvent {
  kind: "thinking";
  timestamp: string | null;
  thinking: string;
  ref: BlockRef | null;
}

export interface TimelineToolUseEvent {
  kind: "tool_use";
  timestamp: string | null;
  name: string;
  input_preview: string;
  ref: BlockRef | null;
}

export interface TimelineToolResultEvent {
  kind: "tool_result";
  timestamp: string | null;
  is_error: boolean;
  content: string;
  ref: BlockRef | null;
}

export type TimelineEvent =
  | TimelineTextEvent
  | TimelineThinkingEvent
  | TimelineToolUseEvent
  | TimelineToolResultEvent;

export interface SessionTimeline {
  session_id: string;
  grain: string;
  bucket: string;
  events: TimelineEvent[];
  truncated: boolean;
}

export interface SessionTranscript {
  session_id: string;
  cursor: number;
  events: TimelineEvent[];
  truncated: boolean;
}

export interface BlockContent {
  text: string;
}

export interface LiveSession {
  session_id: string;
  project: string | null;
  first_prompt: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  turns: number;
}

export interface LiveSessions {
  generated_at: string;
  window_minutes: number;
  sessions: LiveSession[];
}

export interface LiveFeedItem {
  cursor: number;
  session_id: string;
  project: string;
  kind: string;
  is_sidechain: boolean;
  timestamp: string | null;
  preview: string;
}

export interface LiveFeed {
  generated_at: string;
  cursor: number;
  items: LiveFeedItem[];
}

export interface SearchHit {
  source: string;
  line_no: number;
  type: string;
  session_id: string | null;
  timestamp: string | null;
  snippet: string;
}

export interface SearchResults {
  query: string;
  hits: SearchHit[];
}

export interface DataSourceStats {
  name: string;
  db_path: string;
  total_records: number;
  transcript_files: number;
  assistant_records: number;
  assistant_usage_rows: number;
  unique_usage_turns: number;
  duplicate_usage_rows: number;
  first_timestamp: string | null;
  last_timestamp: string | null;
}

export interface DashboardSnapshot {
  generated_at: string;
  totals: DashboardTotals;
  source: DataSourceStats;
  recent_sessions: RecentSession[];
  models: ModelUsage[];
  projects: ProjectUsage[];
  daily: DailyUsage[];
  weekly: TimeUsage[];
  hourly: TimeUsage[];
  five_minute: TimeUsage[];
  notes: string[];
}

export type Grain = "weekly" | "daily" | "hourly" | "five_minute";

async function getJSON<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${url} request failed (${response.status})`);
  return (await response.json()) as T;
}

export const fetchSnapshot = (): Promise<DashboardSnapshot> =>
  getJSON<DashboardSnapshot>("/api/snapshot");

export const fetchTail = (limit = 80): Promise<UsageTail> =>
  getJSON<UsageTail>(`/api/tail?limit=${limit}`);

export const fetchBucket = (grain: string, bucket: string): Promise<BucketDetail> =>
  getJSON<BucketDetail>(`/api/bucket?${new URLSearchParams({ grain, bucket })}`);

export const fetchSessionTimeline = (
  session: string,
  grain: string,
  bucket: string,
): Promise<SessionTimeline> =>
  getJSON<SessionTimeline>(`/api/session-timeline?${new URLSearchParams({ session, grain, bucket })}`);

export const fetchLiveSessions = (window = 30): Promise<LiveSessions> =>
  getJSON<LiveSessions>(`/api/live-sessions?${new URLSearchParams({ window: String(window) })}`);

export const fetchLiveFeed = (after = 0, limit = 100): Promise<LiveFeed> =>
  getJSON<LiveFeed>(
    `/api/live-feed?${new URLSearchParams({ after: String(after), limit: String(limit) })}`,
  );

export const fetchSearch = (q: string, limit = 20): Promise<SearchResults> =>
  getJSON<SearchResults>(`/api/search?${new URLSearchParams({ q, limit: String(limit) })}`);

export const fetchSessionTranscript = (
  session: string,
  after?: number,
): Promise<SessionTranscript> => {
  const params = new URLSearchParams({ session });
  if (after !== undefined) params.set("after", String(after));
  return getJSON<SessionTranscript>(`/api/session-transcript?${params}`);
};

export const fetchBlock = (
  session: string,
  record: number,
  index: number,
): Promise<BlockContent> =>
  getJSON<BlockContent>(
    `/api/block?${new URLSearchParams({ session, record: String(record), index: String(index) })}`,
  );

export interface LogBlock {
  kind: string;
  label: string | null;
  text: string;
  is_error: boolean;
  truncated: boolean;
  tool_use_id: string | null;
}

export interface LogRecord {
  line: number;
  kind: string;
  timestamp: string | null;
  uuid: string | null;
  parent_uuid: string | null;
  is_sidechain: boolean;
  model: string | null;
  request_id: string | null;
  summary: string;
  tokens: TokenBreakdown | null;
  blocks: LogBlock[];
  raw: string;
  raw_truncated: boolean;
}

export interface SessionLog {
  session_id: string;
  file: string;
  offset: number;
  line: number;
  restarted: boolean;
  skipped: number;
  records: LogRecord[];
}

export const fetchSessionLog = (session: string, offset = 0, line = 0): Promise<SessionLog> =>
  getJSON<SessionLog>(
    `/api/session-log?${new URLSearchParams({ session, offset: String(offset), line: String(line) })}`,
  );

// ---------------------------------------------------------------------------
// Context lens — the /timeline/* API (context-token replay over the same sessions)
// ---------------------------------------------------------------------------

export interface SessionRef {
  session_id: string;
  project: string;
  size_bytes: number;
  last_modified: string;
}

export interface ContextEvent {
  kind: "auto" | "user" | "claude" | "hook" | "sub";
  label: string;
  tokens: number;
  estimated: boolean;
  detail: string | null;
}

export interface EventGroup {
  kind: ContextEvent["kind"];
  label: string;
  count: number;
  tokens: number;
  events: ContextEvent[];
}

export interface EventInspection {
  index: number;
  event: ContextEvent;
  content: string;
  content_chars: number;
  truncated: boolean;
}

export interface KindSummary {
  kind: ContextEvent["kind"];
  count: number;
  tokens: number;
}

export interface SessionSummary {
  ref: SessionRef;
  window_tokens: number;
  kinds: KindSummary[];
  total_tokens: number;
  fraction_used: number;
}

export interface ProjectRef {
  project: string;
  session_count: number;
  total_bytes: number;
}

export interface ProjectBreakdown {
  project: string;
  window_tokens: number;
  aggregate: KindSummary[];
  sessions: SessionSummary[];
  total_tokens: number;
  session_count: number;
}

/** Two readings of the same period. `aggregate`/`total_tokens` estimate what filled the context
 *  window, by kind; the token and cost fields are what the API actually billed. They answer
 *  different questions — billed dwarfs the estimate, because cache reads are most of the traffic. */
export interface LedgerBucket {
  label: string;
  starts_on: string;
  ends_on: string;
  session_count: number;
  project_count: number;
  size_bytes: number;
  aggregate: KindSummary[];
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  billed_tokens: number;
  cost_usd: number;
}

export interface LedgerView {
  period: "daily" | "weekly";
  buckets: LedgerBucket[];
  total_tokens: number;
  session_count: number;
}

export interface ContextTimeline {
  source_kind: "session" | "export";
  source: string;
  window_tokens: number;
  events: ContextEvent[];
  total_tokens: number;
  fraction_used: number;
}

export const fetchContextSessions = () => getJSON<SessionRef[]>("/timeline/sessions");

export const fetchContextSession = (session: string, windowTokens?: number) => {
  const params = windowTokens !== undefined ? `?window_tokens=${windowTokens}` : "";
  return getJSON<ContextTimeline>(`/timeline/session/${encodeURIComponent(session)}${params}`);
};

export const fetchContextExport = () => getJSON<ContextTimeline>("/timeline/export");

export const fetchContextGrouped = (session: string) =>
  getJSON<EventGroup[]>(`/timeline/session/${encodeURIComponent(session)}/grouped`);

export const fetchContextEvent = (session: string, index: number) =>
  getJSON<EventInspection>(`/timeline/session/${encodeURIComponent(session)}/event/${index}`);

export const fetchContextProjects = () => getJSON<ProjectRef[]>("/timeline/projects");

export const fetchContextProject = (project: string, windowTokens?: number, limit?: number) => {
  const params = new URLSearchParams();
  if (windowTokens !== undefined) params.set("window_tokens", String(windowTokens));
  if (limit !== undefined) params.set("limit", String(limit));
  const query = params.toString();
  return getJSON<ProjectBreakdown>(
    `/timeline/project/${encodeURIComponent(project)}${query ? `?${query}` : ""}`,
  );
};

export const fetchContextLedger = (period: "daily" | "weekly" = "daily") =>
  getJSON<LedgerView>(`/timeline/ledger?${new URLSearchParams({ period })}`);

export const contextSankeyUrl = (session: string) =>
  `/timeline/session/${encodeURIComponent(session)}/sankey`;

export const contextInvestigationUrl = (session: string, fmt: "markdown" | "json" = "markdown") =>
  `/timeline/session/${encodeURIComponent(session)}/investigation?${new URLSearchParams({ fmt })}`;

export interface SankeyStatTile {
  label: string;
  value: string;
}

export interface SankeyNode {
  id: string;
  label: string;
  tier: number;
  group: string;
}

export interface SankeyLink {
  source: string;
  target: string;
  value: number;
  group: string;
}

export interface SankeyGraph {
  title: string;
  unit: "calls" | "tokens" | "USD";
  nodes: SankeyNode[];
  links: SankeyLink[];
}

export interface SankeySessionPage {
  title: string;
  stats: SankeyStatTile[];
  graphs: SankeyGraph[];
}

export const fetchContextSankeyData = (session: string) =>
  getJSON<SankeySessionPage>(`/timeline/session/${encodeURIComponent(session)}/sankey-data`);
