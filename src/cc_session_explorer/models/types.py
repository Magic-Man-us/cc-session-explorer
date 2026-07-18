from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from cc_session_explorer.types import CostUsd as CostUsd  # re-exported for this lens
from cc_session_explorer.types import TokenCount as TokenCount  # re-exported for this lens

# The largest context window we render against by default (Opus/Sonnet 1M-class windows are
# also valid; this is just the fallback ceiling for the stacked-bar view).
DEFAULT_WINDOW_TOKENS = 200_000
# The 1M-token window the current Opus/Sonnet tiers actually run with — render against this to
# see how full a session really was against its real ceiling.
MILLION_WINDOW_TOKENS = 1_000_000


class EventKind(StrEnum):
    """What produced a context event — drives the colour band in the stacked-bar view. Mirrors
    the kinds in Claude Code's own context-window explorer."""

    auto = "auto"  # loaded before the user types: system prompt, CLAUDE.md, memory, skills, MCP
    user = "user"  # a human turn
    claude = "claude"  # Claude's own work: responses, tool calls, file reads, command output
    hook = "hook"  # a hook firing
    sub = "sub"  # a subagent's context (its own window)


class SourceKind(StrEnum):
    """Where a timeline came from — a replayed real session or a Claude.ai export."""

    session = "session"  # replayed from a real transcript (.jsonl)
    export = "export"  # aggregated from a Claude.ai account data export


class LedgerPeriod(StrEnum):
    """How the Claude Code usage ledger groups sessions."""

    daily = "daily"
    weekly = "weekly"


EventLabel = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        title="Event label",
        description="Short label for one context contribution, e.g. 'Read src/api/auth.ts'.",
        examples=["Read src/api/auth.ts", "Your prompt", "Hook: prettier"],
    ),
]
EventDetail = Annotated[
    str,
    Field(
        max_length=2000,
        title="Event detail",
        description="Optional longer description shown when an event is inspected.",
    ),
]
WindowTokens = Annotated[
    int,
    Field(
        ge=1,
        title="Context window size",
        description="The model's context window the timeline is rendered against.",
        examples=[DEFAULT_WINDOW_TOKENS],
    ),
]
SourceLabel = Annotated[
    str,
    Field(
        min_length=1,
        max_length=200,
        title="Source label",
        description="What produced this timeline — a session id or an export label.",
        examples=["611ed1f6-808f-4665-8b46-7d2211de2761"],
    ),
]
ProjectLabel = Annotated[
    str,
    Field(
        min_length=1,
        max_length=300,
        title="Project label",
        description="The project directory a session transcript belongs to.",
        examples=["-home-user-workplace-my-project"],
    ),
]
SessionByteSize = Annotated[
    int,
    Field(
        ge=0,
        title="Session size",
        description="On-disk size of the session transcript, in bytes.",
        examples=[1048576],
    ),
]
SessionLimit = Annotated[
    int,
    Field(
        ge=1,
        title="Session read limit",
        description="Cap on how many of the largest sessions a project breakdown reads.",
        examples=[50],
    ),
]
GroupLabel = Annotated[
    str,
    # An un-categorised event becomes its own group labelled by its full event label, so this
    # ceiling tracks EventLabel's — never below it, or grouping such a session would fail.
    Field(
        min_length=1,
        max_length=200,
        title="Group label",
        description="A category that collapses many like events, e.g. 'Reads' or 'Bash commands'.",
        examples=["Reads", "Bash commands", "Hooks"],
    ),
]
EventCount = Annotated[
    int,
    Field(
        ge=0,
        title="Event count",
        description="How many events a group collapses.",
        examples=[12],
    ),
]
EventIndex = Annotated[
    int,
    Field(
        ge=0,
        title="Event index",
        description="Zero-based position of an event in a timeline's arrival-ordered chain.",
        examples=[0, 12],
    ),
]
EventContent = Annotated[
    str,
    Field(
        title="Event content",
        description="The raw text an event's token estimate was derived from, capped for "
        "transport; empty when the event carried no text.",
    ),
]
ContentCharCount = Annotated[
    int,
    Field(
        ge=0,
        title="Content character count",
        description="Full character length of the event's source text, before any transport cap.",
        examples=[400],
    ),
]
LedgerBucketLabel = Annotated[
    str,
    Field(
        min_length=1,
        max_length=16,
        title="Ledger bucket label",
        description="Human-stable day or ISO week label, e.g. 2026-07-03 or 2026-W27.",
        examples=["2026-07-03", "2026-W27"],
    ),
]
LedgerDate = Annotated[
    str,
    Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        title="Ledger date",
        description="ISO calendar date bounding one ledger bucket.",
        examples=["2026-07-03"],
    ),
]
