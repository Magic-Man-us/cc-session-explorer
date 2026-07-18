"""Incremental ingest of ``~/.claude/projects/**/*.jsonl`` into the local SQLite store.

Deterministic and model-free: every line is parsed by the typed models, projected onto the
indexed columns, and inserted with its verbatim ``raw`` text and searchable prose. Ingest is
incremental — a file whose size and mtime are unchanged is skipped, and a grown file has only
its tail read: the stored byte offset and hash of the last ingested line verify the boundary
is intact (a live writer may have torn it mid-write), and any mismatch — or a shrunk or
rewritten file — falls back to a whole-file re-ingest. Cost therefore scales with new bytes,
not transcript size. Idempotent: a second run over an unchanged corpus inserts nothing.
Lossless: a line whose envelope does not validate (a torn write, a malformed field) is still
stored verbatim under ``type='invalid'``, never dropped.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from cc_session_core import DEFAULT_PROJECTS_ROOT, Record, message_text, parse_line
from cc_session_core.models import (
    AssistantRecord,
    UserRecord,
)
from cc_session_core.types import Cwd, GitBranch
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from cc_session_explorer.base import FrozenModel
from cc_session_explorer.ingest.kinds import derive_kinds
from cc_session_explorer.ingest.rollup import derive_rollups
from cc_session_explorer.ingest.types import (
    AgentId,
    ByteSize,
    FileCount,
    LineSha,
    MtimeNs,
    ProjectSlug,
    RecordCount,
    RecordUuid,
    SessionId,
    TailOffset,
)
from cc_session_explorer.ingest.usage import derive_usage

if TYPE_CHECKING:
    import sqlite3
    from os import stat_result

logger = logging.getLogger(__name__)

# camelCase envelope keys, unknown fields ignored — the permissive projection config.
TRANSCRIPT_ENVELOPE = ConfigDict(extra="ignore", alias_generator=to_camel, populate_by_name=True)

# The `type` column for a line whose envelope failed validation; the raw line is kept.
_INVALID_TYPE = "invalid"

# Column order here must match the params tuple built in `_ingest_file`.
_INSERT = (
    "INSERT INTO records"
    " (source, line_no, type, uuid, parent_uuid, session_id, timestamp, slug, cwd,"
    " git_branch, agent_id, raw, text)"
    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class RecordRow(BaseModel):
    """The indexed columns lifted off any record's envelope, whatever its ``type``.

    Parsed straight from the raw JSONL line: ``extra='ignore'`` drops the type-specific and
    nested payloads, leaving the shared, queryable columns (present or null).
    """

    model_config = TRANSCRIPT_ENVELOPE
    type: str
    uuid: RecordUuid | None = None
    parent_uuid: RecordUuid | None = None
    session_id: SessionId | None = None
    timestamp: str | None = None
    slug: ProjectSlug | None = None
    cwd: Cwd | None = None
    git_branch: GitBranch | None = None
    agent_id: AgentId | None = None


class IngestReport(FrozenModel):
    """What one ingest run touched."""

    files_total: FileCount
    files_ingested: FileCount
    files_skipped: FileCount
    records_inserted: RecordCount
    parse_errors: RecordCount
    invalid_lines: RecordCount
    usage_priced: RecordCount = 0


class _IngestState(FrozenModel):
    """The per-file high-water mark that makes re-ingest incremental.

    ``tail_offset``/``tail_sha`` locate and fingerprint the last ingested line, so a grown
    file can be read from that offset and trusted only if the boundary line is unchanged.
    """

    lines_ingested: RecordCount
    size_bytes: ByteSize
    mtime_ns: MtimeNs
    tail_offset: TailOffset
    tail_sha: LineSha


class _FileOutcome(FrozenModel):
    inserted: RecordCount
    parse_errors: RecordCount
    invalid_lines: RecordCount


def searchable_text(record: Record) -> str:
    """The record's prose for full-text search: the message text of a conversation turn,
    empty for metadata records (which stay queryable by their columns and ``raw``).
    """
    if isinstance(record, AssistantRecord | UserRecord):
        return message_text(record.message)
    return ""


def _load_state(conn: sqlite3.Connection, source: str) -> _IngestState | None:
    row = conn.execute(
        "SELECT lines_ingested, size_bytes, mtime_ns, tail_offset, tail_sha"
        " FROM ingest_state WHERE source = ?",
        (source,),
    ).fetchone()
    return _IngestState.model_validate(dict(row)) if row is not None else None


def _save_state(conn: sqlite3.Connection, source: str, state: _IngestState) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ingest_state"
        " (source, lines_ingested, size_bytes, mtime_ns, tail_offset, tail_sha)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            source,
            state.lines_ingested,
            state.size_bytes,
            state.mtime_ns,
            state.tail_offset,
            state.tail_sha,
        ),
    )


def _content_lines(text: str) -> list[str]:
    """Non-blank lines, split on ``\\n`` only — never ``str.splitlines()``, which would break
    a line on a ``U+2028``/``U+2029`` embedded inside a JSON string value.
    """
    return [line for line in text.split("\n") if line.strip()]


def _sha(line: str) -> str:
    return hashlib.sha256(line.encode()).hexdigest()


def _decode_lossless(data: bytes) -> str:
    """Decode UTF-8, dropping only bytes torn off mid-write at the tail — never a complete
    line. A live writer's last flush can land inside a multibyte character; the bytes before
    it decode cleanly and the torn remainder heals on the next scan once the write completes.
    """
    try:
        return data.decode()
    except UnicodeDecodeError as exc:
        return data[: exc.start].decode()


def _last_line_offset(data: bytes) -> int:
    """Byte offset, within ``data``, where its last content line starts."""
    return data.rstrip().rfind(b"\n") + 1  # no newline -> -1 + 1 = 0: the region is one line


def _read_tail(
    file: Path, stored: _IngestState, stat: stat_result
) -> tuple[bytes, list[str]] | None:
    """The region from the stored tail offset, when the file strictly grew and the boundary
    line is intact. ``None`` sends the caller down the whole-file path: the file shrank or
    was rewritten, the boundary line changed (it was torn mid-write last run), or the seek
    landed inside a torn multibyte character.
    """
    if stat.st_size <= stored.size_bytes:
        return None
    with file.open("rb") as handle:
        handle.seek(stored.tail_offset)
        data = handle.read()
    try:
        lines = _content_lines(data.decode())
    except UnicodeDecodeError:
        return None
    if not lines or _sha(lines[0]) != stored.tail_sha:
        return None
    return data, lines


def _ingest_file(
    conn: sqlite3.Connection,
    file: Path,
    source: str,
    stored: _IngestState | None,
    stat: stat_result,
) -> _FileOutcome:
    tail = _read_tail(file, stored, stat) if stored is not None else None
    if stored is not None and tail is not None:
        # Verified growth: the boundary line is byte-identical, so only the lines after it
        # are new. Read cost was the tail region, not the file.
        data, region_lines = tail
        insert_lines = region_lines[1:]
        start = stored.lines_ingested
        base = stored.tail_offset
        conn.execute("DELETE FROM records WHERE source = ? AND line_no > ?", (source, start))
    else:
        # New, shrunk, rewritten, or torn-boundary file: re-ingest whole. A line torn by a
        # mid-write read last run fails the boundary hash and heals here.
        data = file.read_bytes()
        region_lines = _content_lines(_decode_lossless(data))
        insert_lines = region_lines
        start = 0
        base = 0
        conn.execute("DELETE FROM records WHERE source = ?", (source,))

    params: list[tuple[object, ...]] = []
    parse_errors = 0
    invalid_lines = 0
    # Each line is deliberately parsed twice — a permissive envelope projection (RecordRow)
    # and the strict typed union (parse_line) — so the failure domains stay independent:
    # a record kind the union can't parse still gets full columns + raw. Measured cost of
    # the second pass: ~0.5s per 150k lines, and only on changed tails.
    for offset, line in enumerate(insert_lines):
        line_no = start + offset + 1
        try:
            row = RecordRow.model_validate_json(line)
        except ValidationError:
            # No valid envelope (torn write, malformed field): keep the raw line anyway.
            logger.warning("%s:%d has no valid envelope — stored as 'invalid'", source, line_no)
            invalid_lines += 1
            params.append((source, line_no, _INVALID_TYPE) + (None,) * 8 + (line, ""))
            continue
        try:
            text = searchable_text(parse_line(line))
        except ValidationError:
            logger.warning("%s:%d failed typed parse — stored raw, no text", source, line_no)
            parse_errors += 1
            text = ""
        params.append(
            (
                source,
                line_no,
                row.type,
                row.uuid,
                row.parent_uuid,
                row.session_id,
                row.timestamp,
                row.slug,
                row.cwd,
                row.git_branch,
                row.agent_id,
                line,
                text,
            )
        )

    conn.executemany(_INSERT, params)
    if region_lines:
        tail_offset = base + _last_line_offset(data)
        tail_sha = _sha(region_lines[-1])
    else:  # a file with no content lines yet
        tail_offset = 0
        tail_sha = _sha("")
    _save_state(
        conn,
        source,
        _IngestState(
            lines_ingested=start + len(insert_lines),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            tail_offset=tail_offset,
            tail_sha=tail_sha,
        ),
    )
    return _FileOutcome(
        inserted=len(params), parse_errors=parse_errors, invalid_lines=invalid_lines
    )


def ingest(conn: sqlite3.Connection, projects_root: Path = DEFAULT_PROJECTS_ROOT) -> IngestReport:
    """Ingest every transcript under ``projects_root`` into ``conn``, incrementally.

    Files unchanged since the last run (same size and mtime) are skipped; the rest are read
    and their new records inserted. Each file's rows and its high-water mark commit together,
    so an interrupted run leaves a consistent store.
    """
    files = sorted(projects_root.rglob("*.jsonl"))
    files_ingested = 0
    files_skipped = 0
    inserted = 0
    parse_errors = 0
    invalid_lines = 0
    for file in files:
        source = str(file.relative_to(projects_root))
        stat = file.stat()
        stored = _load_state(conn, source)
        unchanged = (
            stored is not None
            and stored.size_bytes == stat.st_size
            and stored.mtime_ns == stat.st_mtime_ns
        )
        if unchanged:
            files_skipped += 1
            continue
        with conn:
            outcome = _ingest_file(conn, file, source, stored, stat)
        files_ingested += 1
        inserted += outcome.inserted
        parse_errors += outcome.parse_errors
        invalid_lines += outcome.invalid_lines
    # Both read the records just written, never the transcripts: usage keeps accruing for a
    # session whose file is gone by the next run, and the ledger's rollups are maintained here
    # so a request never has to replay the corpus to get them.
    derive_kinds(conn)
    priced = derive_usage(conn)
    derive_rollups(conn)
    return IngestReport(
        files_total=len(files),
        files_ingested=files_ingested,
        files_skipped=files_skipped,
        records_inserted=inserted,
        parse_errors=parse_errors,
        invalid_lines=invalid_lines,
        usage_priced=priced,
    )
