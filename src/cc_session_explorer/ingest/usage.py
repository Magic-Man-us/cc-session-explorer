"""Priced usage rows, derived from the records already in the store.

One ``usage_events`` row per API request, keyed by core's ``request_key`` so a request's
streaming re-echoes collapse into one. The source is the ``records`` table — not the
transcripts on disk — which is what lets usage outlive transcript rotation: a session
deleted from ``~/.claude/projects`` is still in the archive, so its cost can still be
rebuilt. Derivation is incremental (a watermark over ``records.id``) and idempotent
(conflicting keys are dropped), so re-running it over an unchanged store inserts nothing.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, cast

from cc_session_core import AssistantRecord, parse_line, request_key
from cc_session_core.types import FilePath
from pydantic import BeforeValidator, JsonValue, TypeAdapter, ValidationError

from cc_session_explorer.base import FrozenModel, InputModel
from cc_session_explorer.buckets import bucket_key, project_name, session_key
from cc_session_explorer.history.pricing import (
    DetailedCostInputs,
    estimate_cost,
    estimate_detailed_cost,
)
from cc_session_explorer.ingest.types import SessionId
from cc_session_explorer.types import CostUsd, ModelKey, RequestCount, TokenCount

logger = logging.getLogger(__name__)

CCLEDGER_DB = Path.home() / ".ccledger" / "ccledger.db"

_PROJECT_PARTS = 2
_LEGACY_COMMIT_INTERVAL = 1000
_JSON_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)

_INSERT_USAGE = (
    "INSERT INTO usage_events "
    "(usage_key, source_kind, source, session_id, session_key, project_name, week_bucket, "
    "hour_bucket, five_min_bucket, timestamp, day, project, model, input_tokens, "
    "output_tokens, cache_read_input_tokens, cache_creation_5m_input_tokens, "
    "cache_creation_1h_input_tokens, cache_creation_unknown_tokens, web_search_requests, "
    "web_fetch_requests, service_tier, speed, inference_geo, usage_json, cost_usd, "
    "cost_basis, raw_record_count, inserted_at) "
    "VALUES (:usage_key, :source_kind, :source, :session_id, :session_key, :project_name, "
    ":week_bucket, :hour_bucket, :five_min_bucket, :timestamp, :day, :project, :model, "
    ":input_tokens, :output_tokens, :cache_read_input_tokens, "
    ":cache_creation_5m_input_tokens, :cache_creation_1h_input_tokens, "
    ":cache_creation_unknown_tokens, :web_search_requests, :web_fetch_requests, "
    ":service_tier, :speed, :inference_geo, :usage_json, :cost_usd, :cost_basis, 1, "
    ":inserted_at) "
    "ON CONFLICT(usage_key) DO NOTHING"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _timestamp(value: object) -> datetime | None:
    raw = _text(value)
    if raw is None:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _json_text(value: object) -> str:
    return _JSON_ADAPTER.dump_json(cast("JsonValue", value)).decode("utf-8")


def _legacy_session_id(value: object) -> str | None:
    """ccledger's session id, reduced to the bare session uuid transcripts use.

    It stores the project path with the uuid appended (``-home-user--claude/<uuid>``). Left
    as-is it matches no transcript row, so neither the duplicate check below nor the usage
    lens's disk-is-authoritative merge can ever fire, and the same request is counted twice.
    """
    raw = _text(value)
    if raw is None:
        return None
    return raw.rsplit("/", 1)[-1]


def _project_name(cwd: str | None, fallback_dir: str) -> str | None:
    if cwd:
        parts = [part for part in Path(cwd).parts if part not in ("/", "")]
        if parts:
            return "/".join(parts[-_PROJECT_PARTS:]) if len(parts) >= _PROJECT_PARTS else parts[-1]
    name = fallback_dir.strip("-").replace("-", "/")
    parts = [part for part in name.split("/") if part]
    if parts:
        return "/".join(parts[-_PROJECT_PARTS:]) if len(parts) >= _PROJECT_PARTS else parts[-1]
    return fallback_dir or None


class UsageEventRow(FrozenModel):
    """One priced ``usage_events`` row — the exact shape ``_INSERT_USAGE``'s named params
    expect, whichever pipeline (transcript-derived or legacy-imported) produced it."""

    usage_key: str
    source_kind: Literal["raw_transcript", "ccledger_legacy"]
    source: FilePath | None
    session_id: SessionId | None
    session_key: str | None
    project_name: str | None
    week_bucket: str | None
    hour_bucket: str | None
    five_min_bucket: str | None
    timestamp: str | None
    day: str | None
    project: str | None
    model: ModelKey
    input_tokens: TokenCount
    output_tokens: TokenCount
    cache_read_input_tokens: TokenCount
    cache_creation_5m_input_tokens: TokenCount
    cache_creation_1h_input_tokens: TokenCount
    cache_creation_unknown_tokens: TokenCount
    web_search_requests: RequestCount
    web_fetch_requests: RequestCount
    service_tier: str | None
    speed: str | None
    inference_geo: str | None
    usage_json: str
    cost_usd: CostUsd
    cost_basis: Literal["api_list_detailed", "legacy_flat_cache_write"]
    inserted_at: str


def _usage_row(record: AssistantRecord, source: str, line_no: int) -> UsageEventRow:
    """The usage_events row for one assistant record, straight off the typed model."""
    usage = record.message.usage
    cache = usage.cache_creation
    cache_unknown = max(
        usage.cache_creation_input_tokens
        - cache.ephemeral_5m_input_tokens
        - cache.ephemeral_1h_input_tokens,
        0,
    )
    server = usage.server_tool_use
    stamp = record.timestamp
    if stamp is not None:
        stamp = stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
    key = request_key(record)
    cost_usd = estimate_detailed_cost(
        DetailedCostInputs(
            model=record.message.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cache_creation_5m_tokens=cache.ephemeral_5m_input_tokens,
            cache_creation_1h_tokens=cache.ephemeral_1h_input_tokens,
            cache_creation_unknown_tokens=cache_unknown,
            inference_geo=usage.inference_geo,
        )
    )
    return UsageEventRow(
        # A keyless row can't collapse with its streaming re-echoes; mark it so the
        # accounting views can tell it apart from a real per-request key.
        usage_key=key if key is not None else f"keyless:{source}:{line_no}",
        source_kind="raw_transcript",
        source=source,
        session_id=record.session_id,
        session_key=session_key(source, record.session_id),
        project_name=project_name(source, None),
        week_bucket=bucket_key("weekly", stamp) if stamp is not None else None,
        hour_bucket=bucket_key("hourly", stamp) if stamp is not None else None,
        five_min_bucket=bucket_key("five_minute", stamp) if stamp is not None else None,
        timestamp=stamp.isoformat() if stamp is not None else None,
        day=stamp.date().isoformat() if stamp is not None else None,
        project=_project_name(record.cwd, Path(source).parent.name),
        model=record.message.model,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
        cache_creation_5m_input_tokens=cache.ephemeral_5m_input_tokens,
        cache_creation_1h_input_tokens=cache.ephemeral_1h_input_tokens,
        cache_creation_unknown_tokens=cache_unknown,
        web_search_requests=server.web_search_requests if server is not None else 0,
        web_fetch_requests=server.web_fetch_requests if server is not None else 0,
        service_tier=usage.service_tier,
        speed=usage.speed,
        inference_geo=usage.inference_geo,
        usage_json=usage.model_dump_json(),
        cost_usd=cost_usd,
        cost_basis="api_list_detailed",
        inserted_at=_now(),
    )


def _watermark(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT last_record_id FROM usage_state WHERE id = 1").fetchone()
    return int(row[0]) if row is not None else 0


class _RawTotals:
    """Assistant usage as the transcripts state it, before requests are deduplicated.

    A request that streamed re-echoes its usage on every chunk; `usage_events` keeps one row for
    it, so the count of what was collapsed only survives if it is tallied here on the way past.
    """

    def __init__(self) -> None:
        self.rows = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0

    def add(self, record: AssistantRecord) -> None:
        usage = record.message.usage
        self.rows += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_input_tokens
        self.cache_creation_tokens += usage.cache_creation_input_tokens


def _accumulate_raw(conn: sqlite3.Connection, raw: _RawTotals) -> None:
    if not raw.rows:
        return
    conn.execute(
        "INSERT INTO usage_totals (id, assistant_usage_rows, raw_input_tokens, raw_output_tokens,"
        " raw_cache_read_tokens, raw_cache_creation_tokens) VALUES (1, ?, ?, ?, ?, ?)"
        " ON CONFLICT(id) DO UPDATE SET"
        " assistant_usage_rows = assistant_usage_rows + excluded.assistant_usage_rows,"
        " raw_input_tokens = raw_input_tokens + excluded.raw_input_tokens,"
        " raw_output_tokens = raw_output_tokens + excluded.raw_output_tokens,"
        " raw_cache_read_tokens = raw_cache_read_tokens + excluded.raw_cache_read_tokens,"
        " raw_cache_creation_tokens ="
        " raw_cache_creation_tokens + excluded.raw_cache_creation_tokens",
        (
            raw.rows,
            raw.input_tokens,
            raw.output_tokens,
            raw.cache_read_tokens,
            raw.cache_creation_tokens,
        ),
    )


def derive_usage(conn: sqlite3.Connection) -> int:
    """Price every assistant record the store has gained since the last run; return the count.

    Reads from ``records``, so a session whose transcript has been deleted still yields its
    usage. Records only ever gain higher ids, so the watermark never skips one.
    """
    since = _watermark(conn)
    rows = conn.execute(
        "SELECT id, source, line_no, raw FROM records"
        " WHERE type = 'assistant' AND id > ? ORDER BY id",
        (since,),
    ).fetchall()
    added = 0
    highest = since
    raw = _RawTotals()
    for row in rows:
        highest = int(row["id"])
        try:
            record = parse_line(row["raw"])
        except ValidationError:
            continue
        if not isinstance(record, AssistantRecord):
            continue
        raw.add(record)
        source = str(row["source"])
        line_no = int(row["line_no"])
        before = conn.total_changes
        try:
            usage_row = _usage_row(record, source, line_no)
        except ValidationError:
            logger.warning("%s:%d could not be priced — skipped", source, line_no)
            continue
        conn.execute(_INSERT_USAGE, usage_row.model_dump())
        if conn.total_changes > before:
            added += 1
    _accumulate_raw(conn, raw)
    conn.execute(
        "INSERT INTO usage_state (id, last_record_id) VALUES (1, ?)"
        " ON CONFLICT(id) DO UPDATE SET last_record_id = excluded.last_record_id",
        (highest,),
    )
    conn.commit()
    if added:
        logger.info("priced %d new usage events", added)
    return added


class LegacyCcledgerEvent(InputModel):
    """One row from the retired ccledger ``events`` table (``source = 'code'``), boundary-
    validated before it's translated into a canonical ``UsageEventRow``."""

    uuid: str
    ts: str | None
    day: str | None
    model: Annotated[str, BeforeValidator(lambda v: v or "unknown")]
    project: str | None
    session: str | None
    input_tokens: Annotated[TokenCount, BeforeValidator(lambda v: v or 0)]
    output_tokens: Annotated[TokenCount, BeforeValidator(lambda v: v or 0)]
    cache_read_tokens: Annotated[TokenCount, BeforeValidator(lambda v: v or 0)]
    cache_creation_tokens: Annotated[TokenCount, BeforeValidator(lambda v: v or 0)]


def import_ccledger(conn: sqlite3.Connection, db_path: Path = CCLEDGER_DB) -> int:
    """Import usage from the retired ccledger database; return the count added.

    Predates the transcript archive and has no record to derive from, so these rows are
    carried across verbatim. A row matching a transcript-derived event on its billing
    identity is skipped rather than double-counted.
    """
    if not db_path.exists():
        return 0
    legacy = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    legacy.row_factory = sqlite3.Row
    added = 0
    try:
        rows = legacy.execute(
            "SELECT uuid, ts, day, model, project, session, input_tokens, output_tokens, "
            "cache_read_tokens, cache_creation_tokens FROM events WHERE source = 'code'"
        ).fetchall()
        for row in rows:
            event = LegacyCcledgerEvent.model_validate(dict(row))
            # Transcript rows store normalized UTC ISO timestamps; normalize the legacy one
            # the same way so the equivalence match compares like with like.
            stamp = _timestamp(event.ts)
            ts_text = stamp.isoformat() if stamp is not None else event.ts
            session_id = _legacy_session_id(event.session)
            duplicate = conn.execute(
                "SELECT 1 FROM usage_events WHERE source_kind = 'raw_transcript' "
                "AND session_id IS ? AND timestamp IS ? AND model IS ? "
                "AND input_tokens = ? AND output_tokens = ? AND cache_read_input_tokens = ? "
                "AND (cache_creation_5m_input_tokens + cache_creation_1h_input_tokens + "
                "cache_creation_unknown_tokens) = ? LIMIT 1",
                (
                    session_id,
                    ts_text,
                    event.model,
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_read_tokens,
                    event.cache_creation_tokens,
                ),
            ).fetchone()
            if duplicate is not None:
                continue
            before = conn.total_changes
            usage_row = UsageEventRow(
                usage_key=f"ccledger:{event.uuid}",
                source_kind="ccledger_legacy",
                source=None,
                session_id=session_id,
                session_key=session_key(None, session_id),
                project_name=project_name(None, event.project),
                week_bucket=bucket_key("weekly", stamp) if stamp is not None else None,
                hour_bucket=bucket_key("hourly", stamp) if stamp is not None else None,
                five_min_bucket=bucket_key("five_minute", stamp) if stamp is not None else None,
                timestamp=ts_text,
                day=event.day,
                project=event.project,
                model=event.model,
                input_tokens=event.input_tokens,
                output_tokens=event.output_tokens,
                cache_read_input_tokens=event.cache_read_tokens,
                cache_creation_5m_input_tokens=0,
                cache_creation_1h_input_tokens=0,
                cache_creation_unknown_tokens=event.cache_creation_tokens,
                web_search_requests=0,
                web_fetch_requests=0,
                service_tier=None,
                speed=None,
                inference_geo=None,
                usage_json=_json_text({"source": "ccledger_legacy", "uuid": event.uuid}),
                cost_usd=estimate_cost(
                    event.model,
                    event.input_tokens,
                    event.output_tokens,
                    event.cache_read_tokens,
                    event.cache_creation_tokens,
                ),
                cost_basis="legacy_flat_cache_write",
                inserted_at=_now(),
            )
            conn.execute(_INSERT_USAGE, usage_row.model_dump())
            if conn.total_changes > before:
                added += 1
                if added % _LEGACY_COMMIT_INTERVAL == 0:
                    conn.commit()
    finally:
        legacy.close()
    conn.commit()
    if added:
        logger.info("imported %d legacy usage events from %s", added, db_path)
    return added
