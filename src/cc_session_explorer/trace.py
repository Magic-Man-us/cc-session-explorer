from __future__ import annotations

import json
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from cc_session_core import (
    ParseFailure,
    Session,
    iter_records,
    iter_transcript_records,
    tool_result_text,
)
from cc_session_core.codex.models import (
    CompactedRecord,
    EventMessageRecord,
    GenericEvent,
    RolloutBase,
    SessionMetaRecord,
    TokenCountEvent,
    TurnStartedEvent,
)
from cc_session_core.models import (
    AssistantRecord,
    AttachmentRecord,
    HookNonBlockingError,
    HookSuccess,
    HookSystemMessage,
    Record,
    StartedRecord,
    SystemRecord,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserRecord,
)
from pydantic import BaseModel, JsonValue

from .models import (
    DEFAULT_WINDOW_TOKENS,
    CompactionTrace,
    ContextTrace,
    ContextTraceEvent,
    ContextTraceWindow,
    EventKind,
    TraceEventKind,
    TraceMeasurement,
)
from .sources import Provider
from .tokens import estimate_tokens

_DETAIL_CAP = 1_600
_LABEL_CAP = 196
_SUBAGENT_TOOL_NAMES = frozenset({"agent", "task", "spawn_agent", "spawnagent"})
_CONTEXT_LOAD_LABELS = {
    "skill_listing": "Skills discovered",
    "invoked_skills": "Skills loaded",
    "nested_memory": "Memory loaded",
    "dynamic_skill": "Dynamic skills loaded",
    "file": "File attached",
    "compact_file_reference": "Compact file reference loaded",
    "mcp_instructions_delta": "MCP instructions updated",
    "deferred_tools_delta": "Available tools updated",
    "plan_file_reference": "Plan loaded",
    "command_permissions": "Command permissions loaded",
}
_CODEX_SUBAGENT_EVENTS = frozenset(
    {
        "collab_agent_spawn_begin",
        "collab_agent_spawn_end",
        "collab_agent_interaction_begin",
        "collab_agent_interaction_end",
        "collab_waiting_begin",
        "collab_waiting_end",
        "collab_close_begin",
        "collab_close_end",
        "collab_resume_begin",
        "collab_resume_end",
        "sub_agent_activity",
    }
)
_TRACE_CACHE: OrderedDict[tuple[str, int, int, int | None], ContextTrace] = OrderedDict()
_TRACE_CACHE_MAX = 32


@dataclass(frozen=True, slots=True)
class _TraceSeed:
    timestamp: datetime | None
    kind: TraceEventKind
    label: str
    context_kind: EventKind | None = None
    detail: str | None = None
    token_delta: int = 0
    measurement: TraceMeasurement = TraceMeasurement.estimated
    compaction: CompactionTrace | None = None
    order: int = 0


def _json_text(value: object) -> str:
    if isinstance(value, BaseModel):
        return value.model_dump_json(by_alias=True, exclude_none=True)
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _detail(text: str) -> str | None:
    clean = text.strip()
    if not clean:
        return None
    return clean[:_DETAIL_CAP] + ("…" if len(clean) > _DETAIL_CAP else "")


def _brief(text: str, limit: int = _LABEL_CAP) -> str:
    first = " ".join(text.strip().split())
    return first[:limit] + ("…" if len(first) > limit else "")


def _timestamp(record: object) -> datetime | None:
    value = getattr(record, "timestamp", None)
    return value if isinstance(value, datetime) else None


def _provider_and_records(
    path: Path,
) -> tuple[Provider, list[Record | ParseFailure], list[RolloutBase]]:
    raw = list(iter_transcript_records(path))
    first = next((record for record in raw if not isinstance(record, ParseFailure)), None)
    if isinstance(first, RolloutBase):
        normalized = cast("list[Record | ParseFailure]", list(Session.load(path).records))
        return "codex", normalized, [record for record in raw if isinstance(record, RolloutBase)]
    return "claude", list(iter_records(path)), []


def _tool_label(block: ToolUseBlock) -> str:
    data = block.input
    if isinstance(data, dict):
        values = cast("dict[str, JsonValue]", data)
        for key in ("description", "file_path", "path", "command", "pattern", "query", "url"):
            value = values.get(key)
            if isinstance(value, str) and value:
                return f"{block.name}: {_brief(value, 140)}"
    return str(block.name)


def _is_subagent_tool(name: str) -> bool:
    normalized = name.casefold().replace("-", "_")
    return normalized in _SUBAGENT_TOOL_NAMES or normalized.endswith("__spawn_agent")


def _assistant_seeds(
    record: AssistantRecord,
    provider: Provider,
    tool_names: dict[str, str],
) -> list[_TraceSeed]:
    timestamp = record.timestamp
    context_kind = (
        EventKind.sub
        if record.is_sidechain
        else EventKind.claude
        if provider == "claude"
        else EventKind.codex
    )
    response_label = "Claude response" if provider == "claude" else "Codex response"
    seeds: list[_TraceSeed] = []
    for block in record.message.content:
        if isinstance(block, ThinkingBlock) and block.thinking:
            seeds.append(
                _TraceSeed(
                    timestamp=timestamp,
                    kind=TraceEventKind.thinking,
                    context_kind=context_kind,
                    label="Thinking",
                    detail=_detail(block.thinking),
                    token_delta=estimate_tokens(block.thinking),
                )
            )
        elif isinstance(block, TextBlock) and block.text:
            seeds.append(
                _TraceSeed(
                    timestamp=timestamp,
                    kind=TraceEventKind.response,
                    context_kind=context_kind,
                    label=f"{response_label}: {_brief(block.text, 150)}",
                    detail=_detail(block.text),
                    token_delta=estimate_tokens(block.text),
                )
            )
        elif isinstance(block, ToolUseBlock):
            label = _tool_label(block)
            tool_names[block.id] = label
            raw_input = _json_text(block.input)
            seeds.append(
                _TraceSeed(
                    timestamp=timestamp,
                    kind=(
                        TraceEventKind.subagent
                        if _is_subagent_tool(str(block.name))
                        else TraceEventKind.tool_call
                    ),
                    context_kind=(
                        EventKind.sub if _is_subagent_tool(str(block.name)) else context_kind
                    ),
                    label=(
                        f"Subagent spawned: {_brief(label, 145)}"
                        if _is_subagent_tool(str(block.name))
                        else label
                    ),
                    detail=_detail(raw_input),
                    token_delta=estimate_tokens(raw_input),
                )
            )
    return seeds


def _compact_summary_seed(record: UserRecord, text: str) -> _TraceSeed:
    post_tokens = estimate_tokens(text)
    return _TraceSeed(
        timestamp=record.timestamp,
        kind=TraceEventKind.compaction,
        context_kind=EventKind.auto,
        label="Context compacted into summary",
        detail=_detail(text),
        measurement=TraceMeasurement.inferred,
        compaction=CompactionTrace(post_tokens=post_tokens),
    )


def _user_seeds(
    record: UserRecord,
    provider: Provider,
    tool_names: dict[str, str],
    has_explicit_compaction: bool,
) -> list[_TraceSeed]:
    timestamp = record.timestamp
    context_kind = EventKind.sub if record.is_sidechain else EventKind.user
    provider_kind = (
        EventKind.sub
        if record.is_sidechain
        else EventKind.claude
        if provider == "claude"
        else EventKind.codex
    )
    content = record.message.content
    if isinstance(content, str):
        if record.is_compact_summary and not has_explicit_compaction:
            return [_compact_summary_seed(record, content)]
        return [
            _TraceSeed(
                timestamp=timestamp,
                kind=TraceEventKind.context_load
                if record.is_compact_summary
                else TraceEventKind.prompt,
                context_kind=EventKind.auto if record.is_compact_summary else context_kind,
                label=(
                    "Compaction summary loaded"
                    if record.is_compact_summary
                    else f"User prompt: {_brief(content, 155)}"
                ),
                detail=_detail(content),
                token_delta=estimate_tokens(content),
            )
        ]

    seeds: list[_TraceSeed] = []
    for block in content:
        if isinstance(block, TextBlock) and block.text:
            seeds.append(
                _TraceSeed(
                    timestamp=timestamp,
                    kind=TraceEventKind.prompt,
                    context_kind=context_kind,
                    label=f"User prompt: {_brief(block.text, 155)}",
                    detail=_detail(block.text),
                    token_delta=estimate_tokens(block.text),
                )
            )
        elif isinstance(block, ToolResultBlock):
            text = tool_result_text(block.content)
            seeds.append(
                _TraceSeed(
                    timestamp=timestamp,
                    kind=TraceEventKind.tool_result,
                    context_kind=provider_kind,
                    label=tool_names.get(block.tool_use_id, "Tool result"),
                    detail=_detail(text),
                    token_delta=estimate_tokens(text),
                )
            )
    return seeds


def _attachment_seed(record: AttachmentRecord) -> _TraceSeed | None:
    attachment = record.attachment
    attachment_type = str(attachment.type)
    if isinstance(attachment, HookSuccess):
        text = str(attachment.stdout or attachment.content)
        label = f"Hook completed: {attachment.hook_name or 'hook'}"
        kind = TraceEventKind.hook
    elif isinstance(attachment, HookNonBlockingError):
        text = str(attachment.stdout or attachment.stderr)
        label = f"Hook error: {attachment.hook_name or 'hook'}"
        kind = TraceEventKind.error
    elif isinstance(attachment, HookSystemMessage):
        text = str(attachment.content)
        label = f"Hook context: {attachment.hook_name or 'hook'}"
        kind = TraceEventKind.hook
    elif attachment_type == "task_status":
        text = _json_text(attachment)
        status = getattr(attachment, "status", "updated")
        description = getattr(attachment, "description", "subagent task")
        label = f"Subagent {status}: {_brief(str(description), 135)}"
        kind = TraceEventKind.subagent
    elif attachment_type in _CONTEXT_LOAD_LABELS:
        text = _json_text(attachment)
        label = _CONTEXT_LOAD_LABELS[attachment_type]
        kind = TraceEventKind.context_load
    else:
        return None
    context_kind = (
        EventKind.sub if record.is_sidechain or kind is TraceEventKind.subagent else EventKind.hook
    )
    if kind is TraceEventKind.context_load:
        context_kind = EventKind.auto
    return _TraceSeed(
        timestamp=record.timestamp,
        kind=kind,
        context_kind=context_kind,
        label=label,
        detail=_detail(text),
        token_delta=estimate_tokens(text) if kind is not TraceEventKind.subagent else 0,
        measurement=(
            TraceMeasurement.inferred
            if kind is TraceEventKind.subagent
            else TraceMeasurement.estimated
        ),
    )


def _preserved_count(record: SystemRecord) -> int | None:
    metadata = record.compact_metadata
    if metadata is None or metadata.preserved_messages is None:
        return None
    preserved = metadata.preserved_messages
    if preserved.all_uuids is not None:
        return len(preserved.all_uuids)
    if preserved.uuids is not None:
        return len(preserved.uuids)
    return None


def _system_seed(record: SystemRecord, provider: Provider) -> _TraceSeed | None:
    subtype = str(record.subtype)
    is_compaction = record.compact_metadata is not None or "compact" in subtype.casefold()
    if provider == "codex" and subtype in {"codex_compacted", "codex_compaction"}:
        return None
    if is_compaction:
        metadata = record.compact_metadata
        pre_tokens = metadata.pre_tokens if metadata is not None else None
        post_tokens = metadata.post_tokens if metadata is not None else None
        dropped = (
            max(pre_tokens - post_tokens, 0)
            if pre_tokens is not None and post_tokens is not None
            else None
        )
        return _TraceSeed(
            timestamp=record.timestamp,
            kind=TraceEventKind.compaction,
            context_kind=EventKind.auto,
            label="Context compacted",
            detail=_detail(record.content or ""),
            measurement=(
                TraceMeasurement.exact
                if pre_tokens is not None and post_tokens is not None
                else TraceMeasurement.inferred
            ),
            compaction=CompactionTrace(
                pre_tokens=pre_tokens,
                post_tokens=post_tokens,
                dropped_tokens=dropped,
                trigger=(metadata.trigger if metadata is not None else record.trigger),
                duration_ms=(metadata.duration_ms if metadata is not None else record.duration_ms),
                messages_summarized=(
                    metadata.messages_summarized if metadata is not None else record.message_count
                ),
                cumulative_dropped_tokens=(
                    metadata.cumulative_dropped_tokens if metadata is not None else None
                ),
                preserved_items=_preserved_count(record),
            ),
        )
    if record.error is not None or "error" in subtype.casefold():
        return _TraceSeed(
            timestamp=record.timestamp,
            kind=TraceEventKind.error,
            label=f"System error: {_brief(subtype)}",
            detail=_detail(record.content or _json_text(record.error)),
            measurement=TraceMeasurement.inferred,
        )
    if record.content:
        return _TraceSeed(
            timestamp=record.timestamp,
            kind=TraceEventKind.system,
            label=f"System: {_brief(subtype)}",
            detail=_detail(record.content),
            measurement=TraceMeasurement.inferred,
        )
    return None


def _canonical_seeds(
    records: Iterable[Record | ParseFailure],
    provider: Provider,
) -> list[_TraceSeed]:
    materialized = list(records)
    has_explicit_compaction = any(
        isinstance(record, SystemRecord)
        and (record.compact_metadata is not None or "compact" in str(record.subtype).casefold())
        for record in materialized
    )
    seeds: list[_TraceSeed] = []
    tool_names: dict[str, str] = {}
    last_timestamp: datetime | None = None
    for order, record in enumerate(materialized):
        if isinstance(record, ParseFailure):
            seeds.append(
                _TraceSeed(
                    timestamp=last_timestamp,
                    kind=TraceEventKind.error,
                    label="Transcript record could not be parsed",
                    detail=_detail(record.error),
                    measurement=TraceMeasurement.inferred,
                    order=order,
                )
            )
            continue
        current_timestamp = _timestamp(record) or last_timestamp
        last_timestamp = current_timestamp
        produced: list[_TraceSeed] = []
        if isinstance(record, AssistantRecord):
            produced = _assistant_seeds(record, provider, tool_names)
        elif isinstance(record, UserRecord):
            produced = _user_seeds(record, provider, tool_names, has_explicit_compaction)
        elif isinstance(record, AttachmentRecord):
            attachment = _attachment_seed(record)
            produced = [attachment] if attachment is not None else []
        elif isinstance(record, SystemRecord):
            system = _system_seed(record, provider)
            produced = [system] if system is not None else []
        elif isinstance(record, StartedRecord):
            produced = [
                _TraceSeed(
                    timestamp=current_timestamp,
                    kind=TraceEventKind.subagent,
                    context_kind=EventKind.sub,
                    label=f"Subagent started: {_brief(str(record.key), 145)}",
                    detail=f"agent {record.agent_id}",
                    measurement=TraceMeasurement.inferred,
                )
            ]
        for offset, seed in enumerate(produced):
            seeds.append(
                _TraceSeed(
                    timestamp=seed.timestamp or current_timestamp,
                    kind=seed.kind,
                    label=seed.label,
                    context_kind=seed.context_kind,
                    detail=seed.detail,
                    token_delta=seed.token_delta,
                    measurement=seed.measurement,
                    compaction=seed.compaction,
                    order=order * 100 + offset,
                )
            )
    return seeds


def _codex_window(raw_records: Iterable[RolloutBase]) -> int | None:
    for record in raw_records:
        if not isinstance(record, EventMessageRecord):
            continue
        event = record.payload
        if isinstance(event, TurnStartedEvent) and event.model_context_window is not None:
            return int(event.model_context_window)
        if (
            isinstance(event, TokenCountEvent)
            and event.info is not None
            and event.info.model_context_window is not None
        ):
            return int(event.info.model_context_window)
    return None


def _codex_raw_seeds(raw_records: list[RolloutBase]) -> list[_TraceSeed]:
    seeds: list[_TraceSeed] = []
    has_compacted_record = any(isinstance(record, CompactedRecord) for record in raw_records)
    for order, record in enumerate(raw_records):
        if isinstance(record, SessionMetaRecord):
            payload = record.payload
            loaded: list[tuple[str, object]] = []
            if payload.base_instructions is not None:
                loaded.append(("Base instructions loaded", payload.base_instructions))
            if payload.dynamic_tools:
                loaded.append(("Dynamic tools loaded", payload.dynamic_tools))
            if payload.selected_capability_roots:
                loaded.append(("Capabilities loaded", payload.selected_capability_roots))
            for offset, (label, value) in enumerate(loaded):
                text = _json_text(value)
                seeds.append(
                    _TraceSeed(
                        timestamp=record.timestamp,
                        kind=TraceEventKind.context_load,
                        context_kind=EventKind.auto,
                        label=label,
                        detail=_detail(text),
                        token_delta=estimate_tokens(text),
                        order=order * 100 + offset,
                    )
                )
        elif isinstance(record, CompactedRecord):
            message = record.payload.message
            post_tokens = estimate_tokens(message) if message else None
            seeds.append(
                _TraceSeed(
                    timestamp=record.timestamp,
                    kind=TraceEventKind.compaction,
                    context_kind=EventKind.auto,
                    label="Context compacted",
                    detail=_detail(message),
                    measurement=TraceMeasurement.estimated,
                    compaction=CompactionTrace(
                        post_tokens=post_tokens,
                        window_number=record.payload.window_number,
                        preserved_items=(
                            len(record.payload.replacement_history)
                            if record.payload.replacement_history is not None
                            else None
                        ),
                    ),
                    order=order * 100,
                )
            )
        elif isinstance(record, EventMessageRecord) and isinstance(record.payload, GenericEvent):
            event_type = str(record.payload.type)
            if event_type == "context_compacted" and not has_compacted_record:
                seeds.append(
                    _TraceSeed(
                        timestamp=record.timestamp,
                        kind=TraceEventKind.compaction,
                        context_kind=EventKind.auto,
                        label="Context compacted",
                        detail=_detail(_json_text(record.payload)),
                        measurement=TraceMeasurement.inferred,
                        compaction=CompactionTrace(),
                        order=order * 100,
                    )
                )
            elif event_type in _CODEX_SUBAGENT_EVENTS:
                human = event_type.replace("collab_", "").replace("_", " ")
                seeds.append(
                    _TraceSeed(
                        timestamp=record.timestamp,
                        kind=TraceEventKind.subagent,
                        context_kind=EventKind.sub,
                        label=f"Subagent: {human}",
                        detail=_detail(_json_text(record.payload)),
                        measurement=TraceMeasurement.inferred,
                        order=order * 100,
                    )
                )
    return seeds


def _sort_seeds(seeds: list[_TraceSeed]) -> list[_TraceSeed]:
    dated = [seed.timestamp for seed in seeds if seed.timestamp is not None]
    fallback = min(dated) if dated else datetime.min.replace(tzinfo=UTC)
    return sorted(seeds, key=lambda seed: (seed.timestamp or fallback, seed.order))


def _materialize_events(seeds: list[_TraceSeed]) -> list[ContextTraceEvent]:
    active = 0
    events: list[ContextTraceEvent] = []
    for sequence, seed in enumerate(_sort_seeds(seeds)):
        before = active
        after = max(active + seed.token_delta, 0)
        token_delta = seed.token_delta
        if seed.compaction is not None:
            before = (
                seed.compaction.pre_tokens if seed.compaction.pre_tokens is not None else active
            )
            after = (
                seed.compaction.post_tokens if seed.compaction.post_tokens is not None else active
            )
            token_delta = after - before
        active = after
        events.append(
            ContextTraceEvent(
                sequence=sequence,
                timestamp=seed.timestamp,
                kind=seed.kind,
                context_kind=seed.context_kind,
                label=seed.label,
                detail=seed.detail,
                token_delta=token_delta,
                context_before_tokens=before,
                context_after_tokens=after,
                measurement=seed.measurement,
                compaction=seed.compaction,
            )
        )
    return events


def build_context_trace(path: Path, window_tokens: int | None = None) -> ContextTrace:
    """Build an inspectable active-context and execution trace from one provider transcript."""

    stat = path.stat()
    cache_key = (str(path), stat.st_mtime_ns, stat.st_size, window_tokens)
    cached = _TRACE_CACHE.get(cache_key)
    if cached is not None:
        _TRACE_CACHE.move_to_end(cache_key)
        return cached

    provider, normalized, raw_codex = _provider_and_records(path)
    seeds = _canonical_seeds(normalized, provider)
    if provider == "codex":
        seeds.extend(_codex_raw_seeds(raw_codex))
    events = _materialize_events(seeds)
    timestamps = [event.timestamp for event in events if event.timestamp is not None]
    resolved_window = window_tokens or _codex_window(raw_codex) or DEFAULT_WINDOW_TOKENS
    trace = ContextTrace(
        source=path.stem,
        provider=provider,
        window_tokens=resolved_window,
        started_at=min(timestamps) if timestamps else None,
        ended_at=max(timestamps) if timestamps else None,
        events=events,
    )
    _TRACE_CACHE[cache_key] = trace
    if len(_TRACE_CACHE) > _TRACE_CACHE_MAX:
        _TRACE_CACHE.popitem(last=False)
    return trace


def select_trace_window(
    trace: ContextTrace,
    center: datetime,
    minutes: int = 30,
) -> ContextTraceWindow:
    """Return the symmetric activity window around a selected trace timestamp."""

    if minutes < 1:
        raise ValueError("minutes must be at least 1")
    half = timedelta(minutes=minutes / 2)
    starts_at = center - half
    ends_at = center + half
    return ContextTraceWindow(
        source=trace.source,
        provider=trace.provider,
        center=center,
        starts_at=starts_at,
        ends_at=ends_at,
        minutes=minutes,
        events=[
            event
            for event in trace.events
            if event.timestamp is not None and starts_at <= event.timestamp <= ends_at
        ],
    )
