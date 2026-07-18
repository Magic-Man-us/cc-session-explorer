"""The live-log lens over one transcript: every record, full detail, cursor-tailed.

Where ``transcript.py`` re-derives a clipped user/assistant timeline from a whole-file
reload, this module follows the raw JSONL itself via ``cc_session_core.tail_records`` —
only bytes appended past the cursor are read, and *every* record kind is surfaced:
system events, attachments (hooks, IDE state, plan mode), pointer records, unmodeled
kinds, and parse failures. Each row carries a rendered block view plus the record's
full pretty-printed JSON, so the SPA can show literally everything the CLI wrote.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from cc_session_core import ParseFailure, tail_records, tool_result_text
from cc_session_core.models import (
    AssistantRecord,
    AttachmentRecord,
    ContentBlock,
    ConvBase,
    FallbackBlock,
    ImageBlock,
    RedactedThinkingBlock,
    SystemRecord,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    UserRecord,
)
from pydantic_core import to_json

from cc_session_explorer.usage.models import (
    LogBlock,
    LogRecord,
    SessionLog,
    TokenBreakdown,
)
from cc_session_explorer.usage.scan import session_path

if TYPE_CHECKING:
    from pathlib import Path

    from cc_session_core import Record

_BLOCK_CLIP = 20_000
_RAW_CLIP = 60_000
_MAX_RECORDS = 500


def _clipped(text: str) -> tuple[str, bool]:
    return (text, False) if len(text) <= _BLOCK_CLIP else (text[:_BLOCK_CLIP] + " …", True)


def _pretty(value: object) -> str:
    return to_json(value, indent=2, fallback=str).decode()


def _stamp(value: datetime | str | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else value


def _block(
    kind: str,
    text: str,
    label: str | None = None,
    is_error: bool = False,
    tool_use_id: str | None = None,
) -> LogBlock:
    clipped, truncated = _clipped(text)
    return LogBlock(
        kind=kind,
        label=label,
        text=clipped,
        is_error=is_error,
        truncated=truncated,
        tool_use_id=tool_use_id,
    )


def _image_text(block: ImageBlock) -> str:
    source = block.source
    data = source.get("data") if isinstance(source, dict) else None
    if isinstance(source, dict) and isinstance(data, str):
        source = {**source, "data": f"<{len(data)} chars omitted>"}
    return _pretty(source)


def _content_block(block: ContentBlock) -> LogBlock:
    match block:
        case TextBlock():
            return _block("text", block.text)
        case ThinkingBlock():
            return _block("thinking", block.thinking)
        case RedactedThinkingBlock():
            return _block("redacted_thinking", "[thinking redacted by the API]")
        case ToolUseBlock():
            return _block("tool_use", _pretty(block.input), label=block.name, tool_use_id=block.id)
        case ToolResultBlock():
            return _block(
                "tool_result",
                tool_result_text(block.content),
                is_error=bool(block.is_error),
                tool_use_id=block.tool_use_id,
            )
        case ImageBlock():
            return _block("image", _image_text(block))
        case FallbackBlock():
            return _block("fallback", f"{block.from_} → {block.to}")
        case _:
            return _block("unknown", _pretty(block.model_dump(by_alias=True)), label=block.type)


def _tokens(usage: Usage) -> TokenBreakdown:
    return TokenBreakdown(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_input_tokens,
        cache_creation_tokens=usage.cache_creation_input_tokens,
    )


def _first_line(text: str, limit: int = 140) -> str:
    head = text.strip().splitlines()[0] if text.strip() else ""
    return head if len(head) <= limit else head[:limit] + " …"


def log_summary(record: Record) -> str:
    match record:
        case AssistantRecord():
            parts = [record.message.model]
            if record.message.stop_reason:
                parts.append(f"stop: {record.message.stop_reason}")
            if record.error or record.is_api_error_message:
                parts.append(f"API error: {record.error or record.api_error_status}")
            return " · ".join(str(p) for p in parts)
        case UserRecord():
            flags = [
                name
                for name, on in (
                    ("meta", record.is_meta),
                    ("compact summary", record.is_compact_summary),
                    ("tool result", record.tool_use_result is not None),
                )
                if on
            ]
            content = record.message.content
            head = _first_line(content) if isinstance(content, str) else ""
            return " · ".join(p for p in (", ".join(flags), head) if p) or "user turn"
        case SystemRecord():
            parts = [record.subtype]
            if record.error and record.error.message:
                parts.append(_first_line(record.error.message))
            elif record.content:
                parts.append(_first_line(record.content))
            return " · ".join(parts)
        case AttachmentRecord():
            return record.attachment.type
        case _:
            return record.type


def _record_blocks(record: Record) -> list[LogBlock]:
    match record:
        case AssistantRecord():
            return [_content_block(b) for b in record.message.content]
        case UserRecord():
            content = record.message.content
            blocks = (
                [_block("text", content)]
                if isinstance(content, str)
                else [_content_block(b) for b in content]
            )
            if record.tool_use_result is not None:
                blocks.append(
                    _block("tool_use_result", _pretty(record.tool_use_result), label="parsed")
                )
            return blocks
        case SystemRecord() if record.content:
            return [_block("text", record.content)]
        case AttachmentRecord():
            return [
                _block(
                    "attachment",
                    _pretty(record.attachment.model_dump(by_alias=True)),
                    label=record.attachment.type,
                )
            ]
        case _:
            return []


def _clip_raw(raw: str) -> tuple[str, bool]:
    return (raw, False) if len(raw) <= _RAW_CLIP else (raw[:_RAW_CLIP], True)


def _log_record(record: Record | ParseFailure, line: int) -> LogRecord:
    if isinstance(record, ParseFailure):
        raw, raw_truncated = _clip_raw(record.raw)
        return LogRecord(
            line=line,
            kind="parse_failure",
            summary=_first_line(record.error),
            blocks=[_block("raw_line", record.raw, is_error=True)],
            raw=raw,
            raw_truncated=raw_truncated,
        )
    raw, raw_truncated = _clip_raw(record.model_dump_json(by_alias=True, indent=2))
    usage = record.message.usage if isinstance(record, AssistantRecord) else None
    if isinstance(record, ConvBase):
        timestamp = _stamp(record.timestamp)
        uuid = record.uuid
        parent_uuid = record.parent_uuid
        is_sidechain = bool(record.is_sidechain)
    else:
        timestamp = None
        uuid = None
        parent_uuid = None
        is_sidechain = False
    request_id = record.request_id if isinstance(record, AssistantRecord | SystemRecord) else None
    return LogRecord(
        line=line,
        kind=record.type,
        timestamp=timestamp,
        uuid=uuid,
        parent_uuid=parent_uuid,
        is_sidechain=is_sidechain,
        model=record.message.model if isinstance(record, AssistantRecord) else None,
        request_id=request_id,
        summary=log_summary(record),
        tokens=_tokens(usage) if usage is not None else None,
        blocks=_record_blocks(record),
        raw=raw,
        raw_truncated=raw_truncated,
    )


def build_session_log(
    projects_root: Path, session_id: str, offset: int, line: int
) -> SessionLog | None:
    """The records past the cursor, or None for an unknown/vanished session file."""
    path = session_path(projects_root, session_id)
    if path is None:
        return None
    try:
        batch = tail_records(path, offset, line)
    except FileNotFoundError:
        # The file vanished between the scan and the read — a true 404. Other I/O
        # errors (permissions, transient fs faults) surface as 500s instead.
        return None
    rows = [_log_record(item.record, item.line) for item in batch.records]
    skipped = max(0, len(rows) - _MAX_RECORDS)
    return SessionLog(
        session_id=session_id,
        file=path.name,
        offset=batch.offset,
        line=batch.line,
        restarted=batch.restarted,
        skipped=skipped,
        records=rows[skipped:],
    )
