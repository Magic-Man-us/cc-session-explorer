"""The usage lens's view of the store: priced turns, per-session rollups, and corpus stats.

Every figure here is read back from ``transcripts.db``, which the ingest maintains — nothing is
re-derived from the transcripts on disk. The two dedup layers this used to perform per request
(streaming re-echoes within a file, resumed/forked sessions across files) are settled once, at
ingest, by keying ``usage_events`` on core's ``request_key``.

Reading the store rather than the corpus is also what lets the lens account for a session whose
transcript has been deleted: the archive still holds it, ``~/.claude/projects`` does not.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from cc_session_core.types import FilePath

from cc_session_explorer.base import FrozenModel
from cc_session_explorer.ingest.types import FileCount, RecordCount, SessionId
from cc_session_explorer.paths import resolve_session_path
from cc_session_explorer.sources import (
    Provider,
    ProviderScope,
    TranscriptLocation,
    project_from_storage_key,
    provider_from_storage_key,
    provider_source_predicate,
)
from cc_session_explorer.types import TokenCount

logger = logging.getLogger(__name__)

_FIRST_PROMPT_MAX = 240


class SessionScan(FrozenModel):
    """Per-session rollup read back from the store."""

    session_id: SessionId
    provider: Provider
    project: str
    path: FilePath
    first_prompt: str | None
    first_seen: datetime | None
    last_seen: datetime | None


class ScanResult(FrozenModel):
    """Corpus-wide counters for the data view: how much was archived, and how much collapsed."""

    files: FileCount
    records: RecordCount
    assistant_records: RecordCount
    usage_rows: int
    duplicate_usage_rows: int
    raw_input_tokens: TokenCount
    raw_output_tokens: TokenCount
    raw_cache_read_tokens: TokenCount
    raw_cache_creation_tokens: TokenCount


_EMPTY = ScanResult(
    files=0,
    records=0,
    assistant_records=0,
    usage_rows=0,
    duplicate_usage_rows=0,
    raw_input_tokens=0,
    raw_output_tokens=0,
    raw_cache_read_tokens=0,
    raw_cache_creation_tokens=0,
)


def _utc(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def session_meta(store_db: Path, keys: list[str]) -> dict[str, SessionScan]:
    """Opening prompt, project, and span for the named transcripts, keyed by session.

    Only for the sessions a view actually names — the snapshot lists 40 of 1,068, and rolling up
    every transcript's records to fill in the other 1,028 cost more than all the other queries put
    together.
    """
    if not keys or not store_db.exists():
        return {}
    conn = sqlite3.connect(f"file:{store_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    holes = ",".join("?" * len(keys))
    try:
        # The transcript each session was read from; a legacy session has none and gets no meta.
        sources = {
            str(row["session_key"]): str(row["source"])
            for row in conn.execute(
                "SELECT session_key, source FROM usage_events"
                f" WHERE source IS NOT NULL AND session_key IN ({holes})"
                " GROUP BY session_key",
                keys,
            ).fetchall()
        }
        if not sources:
            return {}
        paths = list(sources.values())
        marks = ",".join("?" * len(paths))
        # SQLite takes a bare column from the row that produced MIN(), so `text` is the first prompt.
        prompts = {
            str(row["source"]): str(row["text"])
            for row in conn.execute(
                "SELECT source, text, MIN(id) FROM records"
                f" WHERE type = 'user' AND text != '' AND source IN ({marks})"
                " GROUP BY source",
                paths,
            ).fetchall()
        }
        spans = {
            str(row["source"]): row
            for row in conn.execute(
                "SELECT source, MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen"
                f" FROM records WHERE source IN ({marks}) GROUP BY source",
                paths,
            ).fetchall()
        }
    except sqlite3.DatabaseError:
        logger.warning("could not read session metadata from %s", store_db)
        return {}
    finally:
        conn.close()

    meta: dict[str, SessionScan] = {}
    for key, source in sources.items():
        span = spans.get(source)
        meta[key] = SessionScan(
            session_id=key,
            provider=provider_from_storage_key(source),
            project=project_from_storage_key(source) or "",
            path=source,
            first_prompt=(prompts.get(source) or "")[:_FIRST_PROMPT_MAX] or None,
            first_seen=_utc(span["first_seen"]) if span is not None else None,
            last_seen=_utc(span["last_seen"]) if span is not None else None,
        )
    return meta


# The store only changes when an ingest runs, so a read is reusable until it does. Keyed by the
# file's stat fingerprint — never object identity, which outlives a GC'd result.
_SCAN_CACHE: dict[str, tuple[tuple[int, int], ScanResult]] = {}


def scan_store(db_path: Path, provider: ProviderScope = "all") -> ScanResult:
    """The lens's whole dataset, read back from the store in a handful of aggregate queries."""
    if not db_path.exists():
        return _EMPTY
    stat = db_path.stat()
    fingerprint = (stat.st_mtime_ns, stat.st_size)
    cache_key = f"{db_path}:{provider}"
    cached = _SCAN_CACHE.get(cache_key)
    if cached is not None and cached[0] == fingerprint:
        return cached[1]
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        source_filter = provider_source_predicate(provider)
        records = conn.execute(f"SELECT COUNT(*) FROM records WHERE {source_filter}").fetchone()[0]
        files = conn.execute(f"SELECT COUNT(*) FROM ingest_state WHERE {source_filter}").fetchone()[
            0
        ]
        assistant_records = conn.execute(
            f"SELECT COUNT(*) FROM records WHERE type = 'assistant' AND {source_filter}"
        ).fetchone()[0]
        raw_where = "1 = 1" if provider == "all" else "provider = ?"
        raw_params = () if provider == "all" else (provider,)
        raw = conn.execute(
            "SELECT COALESCE(SUM(assistant_usage_rows), 0) AS assistant_usage_rows,"
            " COALESCE(SUM(raw_input_tokens), 0) AS raw_input_tokens,"
            " COALESCE(SUM(raw_output_tokens), 0) AS raw_output_tokens,"
            " COALESCE(SUM(raw_cache_read_tokens), 0) AS raw_cache_read_tokens,"
            " COALESCE(SUM(raw_cache_creation_tokens), 0) AS raw_cache_creation_tokens"
            f" FROM provider_usage_totals WHERE {raw_where}",
            raw_params,
        ).fetchone()
        priced = conn.execute(
            "SELECT COUNT(*) FROM usage_events WHERE source_kind = 'raw_transcript'"
            f" AND {source_filter}"
        ).fetchone()[0]
    except sqlite3.DatabaseError:
        logger.warning("could not read %s; serving an empty usage view", db_path)
        return _EMPTY
    finally:
        conn.close()

    usage_rows = int(raw["assistant_usage_rows"]) if raw is not None else 0
    result = ScanResult(
        files=int(files or 0),
        records=int(records or 0),
        assistant_records=int(assistant_records or 0),
        usage_rows=usage_rows,
        # What the dedup collapsed: every assistant usage row the transcripts stated, less the
        # requests they resolved to. Legacy ccledger rows never had a raw row, so they are
        # excluded rather than counted as duplicates of nothing.
        duplicate_usage_rows=max(usage_rows - int(priced), 0),
        raw_input_tokens=int(raw["raw_input_tokens"]) if raw is not None else 0,
        raw_output_tokens=int(raw["raw_output_tokens"]) if raw is not None else 0,
        raw_cache_read_tokens=int(raw["raw_cache_read_tokens"]) if raw is not None else 0,
        raw_cache_creation_tokens=int(raw["raw_cache_creation_tokens"]) if raw is not None else 0,
    )
    _SCAN_CACHE[cache_key] = (fingerprint, result)
    return result


def session_path(projects_root: TranscriptLocation, session_id: str) -> Path | None:
    """The transcript file for ``session_id`` on disk, or None once it has rotated away."""
    return resolve_session_path(projects_root, session_id)
