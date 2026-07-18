"""Per-session transcript views: clipped timeline events, cursor polling, and full blocks.

Events carry a ``ref`` (entry index + part index) only when their text was clipped; the SPA
feeds the ref back to ``/api/block`` for the full body. The transcript cursor is the last
timeline entry index the client has seen — polling with ``after`` returns only newer entries.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cc_session_core import Session
from cc_session_core.report.views import (
    TextPart,
    ThinkingPart,
    TimelineEntry,
    ToolResultPart,
    ToolUsePart,
)
from pydantic_core import to_json

from cc_session_explorer.usage.aggregate import bucket_span
from cc_session_explorer.usage.models import (
    BlockContent,
    BlockRef,
    Role,
    SessionTimeline,
    SessionTranscript,
    TimelineEvent,
    TimelineTextEvent,
    TimelineThinkingEvent,
    TimelineToolResultEvent,
    TimelineToolUseEvent,
)
from cc_session_explorer.usage.scan import session_path

if TYPE_CHECKING:
    from pathlib import Path

_CLIP = 6_000
_MAX_EVENTS = 2_000


def _clip(text: str) -> str:
    return text if len(text) <= _CLIP else text[:_CLIP] + " …"


def _ref(entry_index: int, part_index: int, full: str) -> BlockRef | None:
    return BlockRef(record_id=entry_index, block_index=part_index) if len(full) > _CLIP else None


def _events_from_entry(entry: TimelineEntry) -> list[TimelineEvent]:
    timestamp = entry.timestamp.isoformat() if entry.timestamp is not None else None
    role: Role = "assistant" if entry.role == "assistant" else "user"
    events: list[TimelineEvent] = []
    for index, part in enumerate(entry.parts):
        match part:
            case TextPart():
                events.append(
                    TimelineTextEvent(
                        role=role,
                        timestamp=timestamp,
                        text=_clip(part.text),
                        ref=_ref(entry.index, index, part.text),
                    )
                )
            case ThinkingPart():
                events.append(
                    TimelineThinkingEvent(
                        timestamp=timestamp,
                        thinking=_clip(part.text),
                        ref=_ref(entry.index, index, part.text),
                    )
                )
            case ToolUsePart():
                full = to_json(part.tool_input, indent=2).decode()
                events.append(
                    TimelineToolUseEvent(
                        timestamp=timestamp,
                        name=part.tool_name or "tool",
                        input_preview=_clip(full),
                        ref=_ref(entry.index, index, full),
                    )
                )
            case ToolResultPart():
                events.append(
                    TimelineToolResultEvent(
                        timestamp=timestamp,
                        is_error=bool(part.is_error),
                        content=_clip(part.text),
                        ref=_ref(entry.index, index, part.text),
                    )
                )
            case _:
                continue  # images and unknown block kinds have no dashboard rendering
    return events


def _load_timeline(projects_root: Path, session_id: str) -> list[TimelineEntry] | None:
    path = session_path(projects_root, session_id)
    if path is None:
        return None
    return Session.load(path).timeline()


def build_session_timeline(
    projects_root: Path, session_id: str, grain: str, bucket: str
) -> SessionTimeline | None:
    """The session's events inside one time bucket, or None for an unknown session."""
    entries = _load_timeline(projects_root, session_id)
    if entries is None:
        return None
    span = bucket_span(grain, bucket)
    events: list[TimelineEvent] = []
    for entry in entries:
        if span is not None and (
            entry.timestamp is None or not span[0] <= entry.timestamp < span[1]
        ):
            continue
        events.extend(_events_from_entry(entry))
    truncated = len(events) > _MAX_EVENTS
    return SessionTimeline(
        session_id=session_id,
        grain=grain,
        bucket=bucket,
        events=events[:_MAX_EVENTS],
        truncated=truncated,
    )


def build_transcript(
    projects_root: Path, session_id: str, after: int | None
) -> SessionTranscript | None:
    """The session's events past cursor ``after``, or None for an unknown session."""
    entries = _load_timeline(projects_root, session_id)
    if entries is None:
        return None
    start = after if after is not None else -1
    # The cursor must be the last entry actually delivered — pointing it past a truncation
    # would make the next poll silently skip the cut events.
    cursor = start
    events: list[TimelineEvent] = []
    truncated = False
    for entry in entries:
        if entry.index <= start:
            continue
        entry_events = _events_from_entry(entry)
        if len(events) + len(entry_events) > _MAX_EVENTS:
            truncated = True
            break
        events.extend(entry_events)
        cursor = entry.index
    return SessionTranscript(
        session_id=session_id,
        cursor=cursor,
        events=events,
        truncated=truncated,
    )


def build_block(
    projects_root: Path, session_id: str, record: int, index: int
) -> BlockContent | None:
    """The full, unclipped text of one timeline part, or None if it doesn't exist."""
    entries = _load_timeline(projects_root, session_id)
    if entries is None:
        return None
    entry = next((e for e in entries if e.index == record), None)
    if entry is None or not 0 <= index < len(entry.parts):
        return None
    part = entry.parts[index]
    if isinstance(part, ToolUsePart):
        return BlockContent(text=to_json(part.tool_input, indent=2).decode())
    return BlockContent(text=part.as_text())
