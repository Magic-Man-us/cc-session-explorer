"""Response models for the usage lens — the SPA's `/api/*` contract, field for field.

The frontend consumes these without runtime validation, so names and shapes here are the
contract: snake_case throughout, `TokenBreakdown` on every `tokens` field, and the timeline
event union discriminated on `kind`.
"""

from __future__ import annotations

from typing import Annotated, Literal

from cc_session_core.types import ByteOffset, LineNumber
from pydantic import Field, computed_field

from cc_session_explorer.base import FrozenModel
from cc_session_explorer.ingest import SearchHit
from cc_session_explorer.ingest.types import SessionId
from cc_session_explorer.models.timeline import token_total
from cc_session_explorer.types import CostUsd, ModelKey, TokenCount

Role = Literal["user", "assistant"]


class TokenBreakdown(FrozenModel):
    """The four usage tiers plus their sum; `cache_hit_rate` only where the SPA renders it."""

    input_tokens: TokenCount = 0
    output_tokens: TokenCount = 0
    cache_read_tokens: TokenCount = 0
    cache_creation_tokens: TokenCount = 0
    cache_hit_rate: float | None = None

    @computed_field
    @property
    def total_tokens(self) -> int:
        return token_total(
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_creation_tokens,
        )


class DashboardTotals(FrozenModel):
    tokens: TokenBreakdown
    raw_tokens: TokenBreakdown
    sessions: int
    turns: int
    raw_usage_rows: int
    duplicate_usage_rows: int
    notional_cost_usd: CostUsd


class DataSourceStats(FrozenModel):
    name: str
    db_path: str
    total_records: int
    transcript_files: int
    assistant_records: int
    assistant_usage_rows: int
    unique_usage_turns: int
    duplicate_usage_rows: int
    first_timestamp: str | None
    last_timestamp: str | None


class RecentSession(FrozenModel):
    id: str
    started_at: str | None
    last_seen_at: str | None
    first_prompt: str | None
    project: str | None
    model: ModelKey | None
    tokens: TokenBreakdown
    turns: int
    notional_cost_usd: CostUsd


class ModelUsage(FrozenModel):
    model: ModelKey
    tokens: TokenBreakdown
    turns: int
    sessions: int
    notional_cost_usd: CostUsd


class ProjectUsage(FrozenModel):
    project: str
    tokens: TokenBreakdown
    turns: int
    sessions: int
    notional_cost_usd: CostUsd


class DailyUsage(FrozenModel):
    day: str
    tokens: TokenBreakdown
    turns: int
    sessions: int
    notional_cost_usd: CostUsd


class TimeUsage(FrozenModel):
    bucket: str
    tokens: TokenBreakdown
    turns: int
    sessions: int
    notional_cost_usd: CostUsd


class DashboardSnapshot(FrozenModel):
    generated_at: str
    totals: DashboardTotals
    source: DataSourceStats
    recent_sessions: list[RecentSession]
    models: list[ModelUsage]
    projects: list[ProjectUsage]
    daily: list[DailyUsage]
    weekly: list[TimeUsage]
    hourly: list[TimeUsage]
    five_minute: list[TimeUsage]
    notes: list[str]


class UsageEvent(FrozenModel):
    key: str
    timestamp: str | None
    session_id: SessionId | None
    project: str | None
    model: ModelKey | None
    source_kind: str
    tokens: TokenBreakdown
    notional_cost_usd: CostUsd


class UsageTail(FrozenModel):
    generated_at: str
    total_cost_usd: CostUsd
    events: list[UsageEvent]


class BucketSessionUsage(FrozenModel):
    session_id: SessionId
    project: str | None
    model: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    tokens: TokenBreakdown
    turns: int
    notional_cost_usd: CostUsd


class BucketDetail(FrozenModel):
    grain: str
    bucket: str
    tokens: TokenBreakdown
    turns: int
    sessions: int
    notional_cost_usd: CostUsd
    session_rows: list[BucketSessionUsage]


class BlockRef(FrozenModel):
    record_id: int
    block_index: int


class TimelineTextEvent(FrozenModel):
    kind: Literal["text"] = "text"
    role: Role
    timestamp: str | None
    text: str
    ref: BlockRef | None = None


class TimelineThinkingEvent(FrozenModel):
    kind: Literal["thinking"] = "thinking"
    timestamp: str | None
    thinking: str
    ref: BlockRef | None = None


class TimelineToolUseEvent(FrozenModel):
    kind: Literal["tool_use"] = "tool_use"
    timestamp: str | None
    name: str
    input_preview: str
    ref: BlockRef | None = None


class TimelineToolResultEvent(FrozenModel):
    kind: Literal["tool_result"] = "tool_result"
    timestamp: str | None
    is_error: bool
    content: str
    ref: BlockRef | None = None


TimelineEvent = Annotated[
    TimelineTextEvent | TimelineThinkingEvent | TimelineToolUseEvent | TimelineToolResultEvent,
    Field(discriminator="kind"),
]


class SessionTimeline(FrozenModel):
    session_id: SessionId
    grain: str
    bucket: str
    events: list[TimelineEvent]
    truncated: bool


class SessionTranscript(FrozenModel):
    session_id: SessionId
    cursor: int
    events: list[TimelineEvent]
    truncated: bool


class LiveSession(FrozenModel):
    session_id: SessionId
    project: str | None
    first_prompt: str | None
    first_seen_at: str | None
    last_seen_at: str | None
    turns: int


class LiveSessions(FrozenModel):
    generated_at: str
    window_minutes: int
    sessions: list[LiveSession]


class BlockContent(FrozenModel):
    text: str


class LogBlock(FrozenModel):
    """One rendered content block of a live-log record.

    ``tool_use_id`` is set on both sides of a tool exchange — the ``tool_use`` block's
    own id and the ``tool_result`` block's reference — so the SPA can link the pair.
    """

    kind: str
    label: str | None = None
    text: str
    is_error: bool = False
    truncated: bool = False
    tool_use_id: str | None = None


class LogRecord(FrozenModel):
    """One transcript line, every record kind included, with its full raw JSON."""

    line: int
    kind: str
    timestamp: str | None = None
    uuid: str | None = None
    parent_uuid: str | None = None
    is_sidechain: bool = False
    model: ModelKey | None = None
    request_id: str | None = None
    summary: str
    tokens: TokenBreakdown | None = None
    blocks: list[LogBlock]
    raw: str
    raw_truncated: bool = False


class SessionLog(FrozenModel):
    """A batch of live-log records past the (`offset`, `line`) cursor."""

    session_id: SessionId
    file: str
    offset: ByteOffset
    line: LineNumber
    restarted: bool
    skipped: int
    records: list[LogRecord]


class LiveFeedItem(FrozenModel):
    """One record in the unified cross-session feed: which session it belongs to, and a preview.

    ``session_id`` is the transcript the record was read from, not the record's own sessionId — a
    subagent sidechain carries its parent's id but is its own session here, so the feed is filed
    by transcript. Full detail is fetched per session via ``/session-log``; this stays compact.
    """

    cursor: int
    session_id: SessionId
    project: str
    kind: str
    is_sidechain: bool = False
    timestamp: str | None = None
    preview: str


class LiveFeed(FrozenModel):
    """A batch of feed items past ``after``, newest first, with the cursor to poll from next."""

    generated_at: str
    cursor: int
    items: list[LiveFeedItem]


class SearchResults(FrozenModel):
    """Full-text search results over the local transcript archive, best match first."""

    query: str
    hits: list[SearchHit]
