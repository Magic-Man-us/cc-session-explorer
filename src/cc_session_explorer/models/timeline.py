from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from pydantic import computed_field

from ..base import FrozenModel
from .types import (
    DEFAULT_WINDOW_TOKENS,
    ContentCharCount,
    CostUsd,
    EventContent,
    EventCount,
    EventDetail,
    EventIndex,
    EventKind,
    EventLabel,
    GroupLabel,
    LedgerBucketLabel,
    LedgerDate,
    LedgerPeriod,
    ProjectLabel,
    SessionByteSize,
    SourceKind,
    SourceLabel,
    TokenCount,
    WindowTokens,
)


class _HasTokens(Protocol):
    tokens: TokenCount


def _sum_tokens(items: Iterable[_HasTokens]) -> TokenCount:
    return sum(item.tokens for item in items)


def _fraction_used(total_tokens: TokenCount, window_tokens: WindowTokens) -> float:
    """Filled fraction of the window in [0, 1], clamped so an over-budget run reads as full."""
    return min(total_tokens / window_tokens, 1.0)


def token_total(
    input_tokens: TokenCount,
    output_tokens: TokenCount,
    cache_read_tokens: TokenCount,
    cache_creation_tokens: TokenCount,
) -> TokenCount:
    return input_tokens + output_tokens + cache_read_tokens + cache_creation_tokens


class SessionRef(FrozenModel):
    """A discoverable session transcript on disk — what the explorer's session picker lists."""

    session_id: SourceLabel
    project: ProjectLabel
    size_bytes: SessionByteSize
    last_modified: str


class ContextEvent(FrozenModel):
    """One contribution to the context window, in arrival order — the unit the stacked-bar view
    draws. `estimated` is True when `tokens` is an offline estimate from content length — the
    case for every event today; a later calibration pass will set it False for counts taken from
    a transcript's real `usage` block."""

    kind: EventKind
    label: EventLabel
    tokens: TokenCount
    estimated: bool = True
    detail: EventDetail | None = None


class ContextTimeline(FrozenModel):
    """An ordered run of context events plus the window they fill — the single shape every view
    renders. Every adapter (`from_transcript`, `from_agent_spec`, …) returns this."""

    source_kind: SourceKind
    source: SourceLabel
    window_tokens: WindowTokens = DEFAULT_WINDOW_TOKENS
    events: list[ContextEvent] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> TokenCount:
        """Sum of every event's tokens — the filled height of the bar."""
        return _sum_tokens(self.events)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fraction_used(self) -> float:
        """Filled fraction of the window in [0, 1], clamped so an over-budget run reads as full."""
        return _fraction_used(self.total_tokens, self.window_tokens)


class EventInspection(FrozenModel):
    """One timeline event paired with the raw text its token estimate was derived from — what the
    event-inspection page shows when a bar segment is opened. `content` is capped for transport;
    `content_chars` is the full pre-cap length and `truncated` says whether the cap bit."""

    index: EventIndex
    event: ContextEvent
    content: EventContent = ""
    content_chars: ContentCharCount = 0
    truncated: bool = False


class KindSummary(FrozenModel):
    """A per-kind roll-up of a timeline — the colour bands of the overview/mini bars, no member
    events. The display label for `kind` lives on the client."""

    kind: EventKind
    count: EventCount
    tokens: TokenCount


class EventGroup(FrozenModel):
    """A category that collapses many like events (all the reads, all the hooks) for the grouped,
    expandable full-chain view — carries its member events so a row expands to its detail."""

    kind: EventKind
    label: GroupLabel
    count: EventCount
    tokens: TokenCount
    events: list[ContextEvent] = []


class SessionSummary(FrozenModel):
    """One session as a row in a project breakdown: its ref, totals, and per-kind bands — enough
    for a mini context-window bar without carrying every event. The full chain is fetched on
    drill-down via the session timeline route."""

    ref: SessionRef
    window_tokens: WindowTokens = DEFAULT_WINDOW_TOKENS
    kinds: list[KindSummary] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> TokenCount:
        """Sum of every kind's tokens — the session's filled height."""
        return _sum_tokens(self.kinds)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def fraction_used(self) -> float:
        """Filled fraction of the window in [0, 1], clamped."""
        return _fraction_used(self.total_tokens, self.window_tokens)


class ProjectRef(FrozenModel):
    """A discoverable project — one directory of session transcripts — for the project picker."""

    project: ProjectLabel
    session_count: EventCount
    total_bytes: SessionByteSize


class ProjectBreakdown(FrozenModel):
    """A whole project fully broken down: an aggregate per-kind overview across every session,
    plus one `SessionSummary` per session for the drill-down list."""

    project: ProjectLabel
    window_tokens: WindowTokens = DEFAULT_WINDOW_TOKENS
    aggregate: list[KindSummary] = []
    sessions: list[SessionSummary] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> TokenCount:
        """Total context across every session in the project."""
        return _sum_tokens(self.aggregate)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def session_count(self) -> EventCount:
        """How many sessions the project breaks down into."""
        return len(self.sessions)


class LedgerBucket(FrozenModel):
    """One daily or weekly Claude Code ledger bucket, rolled up across projects.

    Carries both readings of a bucket. `aggregate`/`total_tokens` are the timeline's estimate of
    what *filled the context window*, by kind — content the API never bills for as such. The
    token and cost fields are the API's own accounting of what was *billed*. They answer
    different questions and will not agree; neither is a worse version of the other.
    """

    label: LedgerBucketLabel
    starts_on: LedgerDate
    ends_on: LedgerDate
    session_count: EventCount
    project_count: EventCount
    size_bytes: SessionByteSize
    aggregate: list[KindSummary] = []

    input_tokens: TokenCount = 0
    output_tokens: TokenCount = 0
    cache_read_tokens: TokenCount = 0
    cache_creation_tokens: TokenCount = 0
    cost_usd: CostUsd = 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> TokenCount:
        """Total estimated context tokens in this bucket."""
        return _sum_tokens(self.aggregate)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def billed_tokens(self) -> TokenCount:
        """Total tokens the API actually billed for in this bucket."""
        return token_total(
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_creation_tokens,
        )


class LedgerView(FrozenModel):
    """Daily or weekly Claude Code usage ledger derived from local session transcripts."""

    period: LedgerPeriod
    buckets: list[LedgerBucket] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> TokenCount:
        """Total estimated context tokens across every bucket."""
        return sum(bucket.total_tokens for bucket in self.buckets)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def session_count(self) -> EventCount:
        """How many sessions contributed to the ledger."""
        return sum(bucket.session_count for bucket in self.buckets)
