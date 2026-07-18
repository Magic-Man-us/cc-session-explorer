"""Assemble the SPA's snapshot, tail, bucket, and live views out of the store's maintained rollups.

Nothing here sums usage. The ingest accumulates every total the lens shows — by model, project,
session, and four time grains — as the rows land, so a view reads a handful of rows keyed by the
dimension it wants instead of aggregating ~200k on each request.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cc_session_core import parse_line
from pydantic import ValidationError

from cc_session_explorer.buckets import bucket_span as bucket_span  # re-export: transcript.py
from cc_session_explorer.buckets import project_name, session_key
from cc_session_explorer.ingest import search_readonly
from cc_session_explorer.ingest.rollup import DIMENSIONS
from cc_session_explorer.usage.livelog import log_summary
from cc_session_explorer.usage.models import (
    BucketDetail,
    BucketSessionUsage,
    DailyUsage,
    DashboardSnapshot,
    DashboardTotals,
    DataSourceStats,
    LiveFeed,
    LiveFeedItem,
    LiveSession,
    LiveSessions,
    ModelUsage,
    ProjectUsage,
    RecentSession,
    SearchResults,
    TimeUsage,
    TokenBreakdown,
    UsageEvent,
    UsageTail,
)
from cc_session_explorer.usage.scan import ScanResult, scan_store, session_meta

logger = logging.getLogger(__name__)

_RECENT_SESSIONS_MAX = 40
_PREVIEW_MAX = 200
_SOURCE_NAME = "claude code transcripts (cc-session-core, stateless)"
_NOTES = [
    "Costs are API-list estimates computed from transcript usage, not provider billing.",
    "Turns are deduplicated by request id within and across session files.",
    "Usage is priced from the record archive, so a session whose transcript has been deleted "
    "still counts.",
]

# The rollup dimension each time grain is accumulated under, and the usage_events column that
# carries its key (for the one query that still has to reach past the rollups).
_GRAINS = {"daily": "day", "weekly": "week", "hourly": "hour", "five_minute": "five_min"}
_DIMENSION_COLUMNS = dict(DIMENSIONS)
_GRAIN_COLUMNS = {grain: _DIMENSION_COLUMNS[dimension] for grain, dimension in _GRAINS.items()}

# A distinct-session count is the one figure a running total cannot carry, so membership is kept
# and counted here.
_ROLLUP = (
    "SELECT r.key AS key, r.input_tokens, r.output_tokens, r.cache_read_tokens,"
    " r.cache_creation_tokens, r.turns, r.cost_usd, r.first_seen, r.last_seen, r.model,"
    " (SELECT COUNT(*) FROM usage_rollup_sessions s"
    "    WHERE s.dimension = r.dimension AND s.key = r.key) AS sessions"
    " FROM usage_rollup r WHERE r.dimension = ?"
)

_EMPTY_TOKENS = TokenBreakdown(
    input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_creation_tokens=0
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _iso(value: object) -> str | None:
    """A stored timestamp, normalised to the ISO-8601 UTC form the SPA already receives."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    stamp = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return stamp.isoformat()


def _tokens(row: sqlite3.Row, *, hit_rate: bool = False) -> TokenBreakdown:
    read = int(row["cache_read_tokens"])
    written = int(row["cache_creation_tokens"])
    prompt = int(row["input_tokens"])
    rate: float | None = None
    if hit_rate:
        read_or_written = prompt + read + written
        rate = read / read_or_written if read_or_written else None
    return TokenBreakdown(
        input_tokens=prompt,
        output_tokens=int(row["output_tokens"]),
        cache_read_tokens=read,
        cache_creation_tokens=written,
        cache_hit_rate=rate,
    )


def _open(store_db: Path) -> sqlite3.Connection | None:
    """The store, read-only, or None when it cannot be read — the views then serve empty.

    A crashed ingest can leave a corrupt file and a read-only mount can strand a hot WAL, so the
    connection is probed here rather than left to blow up inside a view: a dashboard with no
    numbers beats a dashboard that 500s.
    """
    if not store_db.exists():
        return None
    conn = sqlite3.connect(f"file:{store_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("SELECT 1 FROM usage_rollup LIMIT 1").fetchone()
    except sqlite3.DatabaseError:
        logger.warning("could not read %s; serving empty usage views", store_db)
        conn.close()
        return None
    return conn


def _dimension(conn: sqlite3.Connection, dimension: str, order: str) -> list[sqlite3.Row]:
    return conn.execute(f"{_ROLLUP} ORDER BY {order}", (dimension,)).fetchall()  # noqa: S608


def _total(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(f"{_ROLLUP} AND r.key = ''", ("total",)).fetchone()  # noqa: S608


def _time_usage(rows: list[sqlite3.Row]) -> list[TimeUsage]:
    return [
        TimeUsage(
            bucket=str(row["key"]),
            tokens=_tokens(row),
            turns=int(row["turns"]),
            sessions=int(row["sessions"]),
            notional_cost_usd=round(float(row["cost_usd"]), 4),
        )
        for row in rows
    ]


def _totals(row: sqlite3.Row | None, corpus: ScanResult) -> DashboardTotals:
    raw = TokenBreakdown(
        input_tokens=corpus.raw_input_tokens,
        output_tokens=corpus.raw_output_tokens,
        cache_read_tokens=corpus.raw_cache_read_tokens,
        cache_creation_tokens=corpus.raw_cache_creation_tokens,
    )
    return DashboardTotals(
        tokens=_tokens(row, hit_rate=True) if row is not None else _EMPTY_TOKENS,
        raw_tokens=raw,
        sessions=int(row["sessions"]) if row is not None else 0,
        turns=int(row["turns"]) if row is not None else 0,
        raw_usage_rows=corpus.usage_rows,
        duplicate_usage_rows=corpus.duplicate_usage_rows,
        notional_cost_usd=round(float(row["cost_usd"]), 4) if row is not None else 0.0,
    )


def _source(row: sqlite3.Row | None, corpus: ScanResult, store_db: Path) -> DataSourceStats:
    return DataSourceStats(
        name=_SOURCE_NAME,
        db_path=str(store_db),
        total_records=corpus.records,
        transcript_files=corpus.files,
        assistant_records=corpus.assistant_records,
        assistant_usage_rows=corpus.usage_rows,
        unique_usage_turns=int(row["turns"]) if row is not None else 0,
        duplicate_usage_rows=corpus.duplicate_usage_rows,
        first_timestamp=_iso(row["first_seen"]) if row is not None else None,
        last_timestamp=_iso(row["last_seen"]) if row is not None else None,
    )


def _recent_sessions(conn: sqlite3.Connection, store_db: Path) -> list[RecentSession]:
    rows = conn.execute(
        f"{_ROLLUP} ORDER BY r.last_seen DESC LIMIT ?",  # noqa: S608
        ("session", _RECENT_SESSIONS_MAX),
    ).fetchall()
    meta = session_meta(store_db, [str(row["key"]) for row in rows])
    return [
        RecentSession(
            id=str(row["key"]),
            started_at=_iso(row["first_seen"]),
            last_seen_at=_iso(row["last_seen"]),
            first_prompt=meta[str(row["key"])].first_prompt if str(row["key"]) in meta else None,
            project=meta[str(row["key"])].project if str(row["key"]) in meta else None,
            model=str(row["model"]) if row["model"] else None,
            tokens=_tokens(row),
            turns=int(row["turns"]),
            notional_cost_usd=round(float(row["cost_usd"]), 4),
        )
        for row in rows
    ]


def _empty_stats(store_db: Path) -> DataSourceStats:
    return DataSourceStats(
        name=_SOURCE_NAME,
        db_path=str(store_db),
        total_records=0,
        transcript_files=0,
        assistant_records=0,
        assistant_usage_rows=0,
        unique_usage_turns=0,
        duplicate_usage_rows=0,
        first_timestamp=None,
        last_timestamp=None,
    )


def _empty_snapshot(store_db: Path) -> DashboardSnapshot:
    return DashboardSnapshot(
        generated_at=_now(),
        totals=DashboardTotals(
            tokens=_EMPTY_TOKENS,
            raw_tokens=_EMPTY_TOKENS,
            sessions=0,
            turns=0,
            raw_usage_rows=0,
            duplicate_usage_rows=0,
            notional_cost_usd=0.0,
        ),
        source=_empty_stats(store_db),
        recent_sessions=[],
        models=[],
        projects=[],
        daily=[],
        weekly=[],
        hourly=[],
        five_minute=[],
        notes=list(_NOTES),
    )


def build_snapshot(store_db: Path) -> DashboardSnapshot:
    """The one payload behind most of the SPA: totals, rollups, and time buckets."""
    conn = _open(store_db)
    if conn is None:
        return _empty_snapshot(store_db)
    corpus = scan_store(store_db)
    try:
        overall = _total(conn)
        buckets = {
            grain: _time_usage(_dimension(conn, dimension, "r.key"))
            for grain, dimension in _GRAINS.items()
        }
        return DashboardSnapshot(
            generated_at=_now(),
            totals=_totals(overall, corpus),
            source=_source(overall, corpus, store_db),
            recent_sessions=_recent_sessions(conn, store_db),
            models=[
                ModelUsage(
                    model=str(row["key"] or "unknown"),
                    tokens=_tokens(row),
                    turns=int(row["turns"]),
                    sessions=int(row["sessions"]),
                    notional_cost_usd=round(float(row["cost_usd"]), 4),
                )
                for row in _dimension(conn, "model", "r.cost_usd DESC")
            ],
            projects=[
                ProjectUsage(
                    project=str(row["key"] or ""),
                    tokens=_tokens(row),
                    turns=int(row["turns"]),
                    sessions=int(row["sessions"]),
                    notional_cost_usd=round(float(row["cost_usd"]), 4),
                )
                for row in _dimension(conn, "project", "r.cost_usd DESC")
            ],
            daily=[
                DailyUsage(
                    day=row.bucket,
                    tokens=row.tokens,
                    turns=row.turns,
                    sessions=row.sessions,
                    notional_cost_usd=row.notional_cost_usd,
                )
                for row in buckets["daily"]
            ],
            weekly=buckets["weekly"],
            hourly=buckets["hourly"],
            five_minute=buckets["five_minute"],
            notes=list(_NOTES),
        )
    finally:
        conn.close()


def build_tail(store_db: Path, limit: int) -> UsageTail:
    """The most recent ``limit`` usage turns, newest first."""
    conn = _open(store_db)
    if conn is None:
        return UsageTail(generated_at=_now(), total_cost_usd=0.0, events=[])
    try:
        overall = _total(conn)
        rows = conn.execute(
            "SELECT usage_key, timestamp, session_key, project_name, model, input_tokens,"
            " output_tokens, cache_read_input_tokens AS cache_read_tokens,"
            " cache_creation_5m_input_tokens + cache_creation_1h_input_tokens"
            " + cache_creation_unknown_tokens AS cache_creation_tokens, cost_usd"
            " FROM usage_events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    return UsageTail(
        generated_at=_now(),
        total_cost_usd=round(float(overall["cost_usd"]), 4) if overall is not None else 0.0,
        events=[
            UsageEvent(
                key=str(row["usage_key"]),
                timestamp=_iso(row["timestamp"]),
                session_id=str(row["session_key"]) if row["session_key"] else None,
                project=str(row["project_name"]) if row["project_name"] else None,
                model=str(row["model"]) if row["model"] else None,
                source_kind="transcript",
                tokens=_tokens(row),
                notional_cost_usd=round(float(row["cost_usd"]), 4),
            )
            for row in rows
        ],
    )


def build_bucket(store_db: Path, grain: str, bucket: str) -> BucketDetail | None:
    """One time bucket expanded into its per-session rows.

    An unreadable/missing store or an unrecognised grain serves the dashboard's empty shape
    (matching every other view here). A valid store with no rows for this (grain, bucket) pair is
    a genuine miss and returns None, for the route to 404 like its sibling identifier lookups.
    """
    conn = _open(store_db)
    if conn is None or grain not in _GRAINS:
        if conn is not None:
            conn.close()
        return BucketDetail(
            grain=grain,
            bucket=bucket,
            tokens=_EMPTY_TOKENS,
            turns=0,
            sessions=0,
            notional_cost_usd=0.0,
            session_rows=[],
        )
    try:
        overall = conn.execute(
            f"{_ROLLUP} AND r.key = ?",  # noqa: S608
            (_GRAINS[grain], bucket),
        ).fetchone()
        if overall is None:
            return None
        # The per-session split of one bucket is the one figure not worth its own rollup: it is
        # (grain x bucket x session), and it is only ever asked for one bucket, off an index.
        rows = conn.execute(
            "SELECT session_key, model,"
            " COALESCE(SUM(input_tokens), 0) AS input_tokens,"
            " COALESCE(SUM(output_tokens), 0) AS output_tokens,"
            " COALESCE(SUM(cache_read_input_tokens), 0) AS cache_read_tokens,"
            " COALESCE(SUM(cache_creation_5m_input_tokens + cache_creation_1h_input_tokens"
            " + cache_creation_unknown_tokens), 0) AS cache_creation_tokens,"
            " COUNT(*) AS turns, COALESCE(SUM(cost_usd), 0.0) AS cost_usd,"
            " MIN(timestamp) AS first_seen, MAX(timestamp) AS last_seen"
            f" FROM usage_events WHERE {_GRAIN_COLUMNS[grain]} = ?"  # noqa: S608
            " GROUP BY session_key ORDER BY cost_usd DESC",
            (bucket,),
        ).fetchall()
    finally:
        conn.close()
    meta = session_meta(store_db, [str(row["session_key"]) for row in rows])
    return BucketDetail(
        grain=grain,
        bucket=bucket,
        tokens=_tokens(overall),
        turns=int(overall["turns"]),
        sessions=int(overall["sessions"]),
        notional_cost_usd=round(float(overall["cost_usd"]), 4),
        session_rows=[
            BucketSessionUsage(
                session_id=str(row["session_key"]),
                project=meta[str(row["session_key"])].project
                if str(row["session_key"]) in meta
                else None,
                model=str(row["model"]) if row["model"] else None,
                first_seen_at=_iso(row["first_seen"]),
                last_seen_at=_iso(row["last_seen"]),
                tokens=_tokens(row),
                turns=int(row["turns"]),
                notional_cost_usd=round(float(row["cost_usd"]), 4),
            )
            for row in rows
        ],
    )


def build_live_sessions(store_db: Path, window_minutes: int) -> LiveSessions:
    """Sessions with activity inside the trailing window, most recent first.

    Sourced from the store, so this trails a live session by the watcher's debounce — immaterial
    against a window measured in minutes, and it costs one keyed read instead of a corpus walk.
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=window_minutes)
    conn = _open(store_db)
    if conn is None:
        return LiveSessions(generated_at=_now(), window_minutes=window_minutes, sessions=[])
    try:
        rows = conn.execute(
            "SELECT key, turns, first_seen, last_seen FROM usage_rollup"
            " WHERE dimension = 'session' AND last_seen >= ? ORDER BY last_seen DESC",
            (cutoff.isoformat(),),
        ).fetchall()
    finally:
        conn.close()
    meta = session_meta(store_db, [str(row["key"]) for row in rows])
    return LiveSessions(
        generated_at=_now(),
        window_minutes=window_minutes,
        sessions=[
            LiveSession(
                session_id=str(row["key"]),
                project=meta[str(row["key"])].project if str(row["key"]) in meta else "",
                first_prompt=meta[str(row["key"])].first_prompt
                if str(row["key"]) in meta
                else None,
                first_seen_at=_iso(row["first_seen"]),
                last_seen_at=_iso(row["last_seen"]),
                turns=int(row["turns"]),
            )
            for row in rows
        ],
    )


def _preview(text: object, raw: object, kind: str) -> str:
    """A one-line gist of a record for the feed row.

    Its prose if it has any; otherwise the same per-record summary the drill-down log shows (a
    tool-only turn, a hook, a mode change carry no prose but are not nothing), parsed from the
    stored raw line. Kind is the last resort for a line that will not even parse.
    """
    if isinstance(text, str) and text.strip():
        line = next((part for part in text.splitlines() if part.strip()), "")
        return line[:_PREVIEW_MAX].strip()
    if isinstance(raw, str) and raw:
        try:
            summary = log_summary(parse_line(raw))
        except ValidationError:
            summary = ""
        if summary.strip():
            return summary[:_PREVIEW_MAX].strip()
    return f"({kind})"


def build_live_feed(store_db: Path, after: int, limit: int) -> LiveFeed:
    """Every record ingested after cursor ``after``, newest first, each filed to its session.

    Reads the record archive the watcher keeps current, so the feed spans all sessions at once and
    a record is filed by the transcript it came from — the reliable discriminator, since a subagent
    sidechain carries its parent's sessionId but is its own transcript. ``records.id`` only grows,
    so ``after`` is a stable cursor: poll with the returned ``cursor`` to get only what is new.
    """
    if not store_db.exists():
        return LiveFeed(generated_at=_now(), cursor=after, items=[])
    conn = sqlite3.connect(f"file:{store_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT id, source, session_id, type, timestamp, text, raw"
            " FROM records WHERE id > ? ORDER BY id DESC LIMIT ?",
            (after, limit),
        ).fetchall()
    except sqlite3.DatabaseError:
        logger.warning("could not read %s; serving an empty feed", store_db)
        return LiveFeed(generated_at=_now(), cursor=after, items=[])
    finally:
        conn.close()
    # DESC, so the first row is the newest and its id is the high-water mark to poll from next.
    cursor = int(rows[0]["id"]) if rows else after
    items: list[LiveFeedItem] = []
    for row in rows:
        session = session_key(str(row["source"]), row["session_id"]) or ""
        items.append(
            LiveFeedItem(
                cursor=int(row["id"]),
                session_id=session,
                project=project_name(str(row["source"]), None) or "",
                kind=str(row["type"]),
                # A record whose own sessionId is not its transcript is a subagent sidechain,
                # filed here to the transcript it actually lives in.
                is_sidechain=bool(row["session_id"]) and str(row["session_id"]) != session,
                timestamp=_iso(row["timestamp"]),
                preview=_preview(row["text"], row["raw"], str(row["type"])),
            )
        )
    return LiveFeed(generated_at=_now(), cursor=cursor, items=items)


def build_search(transcripts_db: Path, q: str, limit: int) -> SearchResults:
    """Full-text search over the local transcript archive, best match first."""
    return SearchResults(query=q, hits=search_readonly(transcripts_db, q, limit))
