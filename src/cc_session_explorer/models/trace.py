from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, computed_field

from ..base import FrozenModel
from ..sources import Provider
from .types import DEFAULT_WINDOW_TOKENS, EventKind, TokenCount, WindowTokens


class TraceEventKind(StrEnum):
    """A provider-neutral activity type rendered on the session trace."""

    context_load = "context_load"
    prompt = "prompt"
    thinking = "thinking"
    response = "response"
    tool_call = "tool_call"
    tool_result = "tool_result"
    hook = "hook"
    subagent = "subagent"
    compaction = "compaction"
    system = "system"
    error = "error"


class TraceMeasurement(StrEnum):
    """How confidently the active-context count at an event is known."""

    exact = "exact"
    estimated = "estimated"
    inferred = "inferred"


class CompactionTrace(FrozenModel):
    """Provider-neutral details for one context compaction boundary."""

    pre_tokens: TokenCount | None = None
    post_tokens: TokenCount | None = None
    dropped_tokens: TokenCount | None = None
    trigger: str | None = Field(default=None, max_length=200)
    duration_ms: int | None = Field(default=None, ge=0)
    messages_summarized: int | None = Field(default=None, ge=0)
    cumulative_dropped_tokens: TokenCount | None = None
    preserved_items: int | None = Field(default=None, ge=0)
    window_number: int | None = Field(default=None, ge=0)


class ContextTraceEvent(FrozenModel):
    """One point on the context-growth line and one inspectable activity event."""

    sequence: int = Field(ge=0)
    timestamp: datetime | None = None
    kind: TraceEventKind
    context_kind: EventKind | None = None
    label: str = Field(min_length=1, max_length=200)
    detail: str | None = Field(default=None, max_length=2000)
    token_delta: int = 0
    context_before_tokens: TokenCount = 0
    context_after_tokens: TokenCount = 0
    measurement: TraceMeasurement = TraceMeasurement.estimated
    compaction: CompactionTrace | None = None


class ContextTrace(FrozenModel):
    """The complete context-growth and activity trace for one recorded session."""

    source: str = Field(min_length=1, max_length=200)
    provider: Provider
    window_tokens: WindowTokens = DEFAULT_WINDOW_TOKENS
    started_at: datetime | None = None
    ended_at: datetime | None = None
    events: list[ContextTraceEvent] = Field(default_factory=lambda: list[ContextTraceEvent]())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def peak_tokens(self) -> TokenCount:
        return max(
            (
                max(
                    event.context_before_tokens,
                    event.context_after_tokens,
                    event.compaction.pre_tokens
                    if event.compaction and event.compaction.pre_tokens is not None
                    else 0,
                )
                for event in self.events
            ),
            default=0,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def final_tokens(self) -> TokenCount:
        return self.events[-1].context_after_tokens if self.events else 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def compaction_count(self) -> int:
        return sum(event.kind is TraceEventKind.compaction for event in self.events)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def subagent_count(self) -> int:
        return sum(event.kind is TraceEventKind.subagent for event in self.events)


class ContextTraceWindow(FrozenModel):
    """A selected time slice centered on one trace event."""

    source: str = Field(min_length=1, max_length=200)
    provider: Provider
    center: datetime
    starts_at: datetime
    ends_at: datetime
    minutes: int = Field(ge=1)
    events: list[ContextTraceEvent] = Field(default_factory=lambda: list[ContextTraceEvent]())
