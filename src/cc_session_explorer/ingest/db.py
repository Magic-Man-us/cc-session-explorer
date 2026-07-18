"""The local SQLite store for transcript records: schema, connection, and full-text search.

Every record is one row: a handful of indexed columns lifted off the envelope, the verbatim
JSONL line (``raw``) so nothing is ever lost, and the record's searchable prose (``text``).
An external-content FTS5 index over ``text`` — kept in sync by triggers — backs
``search``. The database is local and owner-only (``0600``): transcripts can contain pasted
secrets, so it never leaves the machine.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from cc_session_core.types import FilePath

from cc_session_explorer.base import InputModel
from cc_session_explorer.ingest.types import LineNumber, SessionId
from cc_session_explorer.paths import DATA_HOME, TRANSCRIPTS_DB_NAME

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_DIR_MODE = 0o700
_FILE_MODE = 0o600
_DEFAULT_SEARCH_LIMIT = 20

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,
    line_no     INTEGER NOT NULL,
    type        TEXT NOT NULL,
    uuid        TEXT,
    parent_uuid TEXT,
    session_id  TEXT,
    timestamp   TEXT,
    slug        TEXT,
    cwd         TEXT,
    git_branch  TEXT,
    agent_id    TEXT,
    raw         TEXT NOT NULL,
    text        TEXT NOT NULL,
    UNIQUE (source, line_no)
);

CREATE INDEX IF NOT EXISTS idx_records_uuid ON records (uuid);
CREATE INDEX IF NOT EXISTS idx_records_session ON records (session_id);
CREATE INDEX IF NOT EXISTS idx_records_type ON records (type);
CREATE INDEX IF NOT EXISTS idx_records_timestamp ON records (timestamp);

CREATE VIRTUAL TABLE IF NOT EXISTS records_fts
    USING fts5 (text, content='records', content_rowid='id');

CREATE TRIGGER IF NOT EXISTS records_ai AFTER INSERT ON records BEGIN
    INSERT INTO records_fts (rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS records_ad AFTER DELETE ON records BEGIN
    INSERT INTO records_fts (records_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS records_au AFTER UPDATE ON records BEGIN
    INSERT INTO records_fts (records_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO records_fts (rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS ingest_state (
    source         TEXT PRIMARY KEY,
    lines_ingested INTEGER NOT NULL,
    size_bytes     INTEGER NOT NULL,
    mtime_ns       INTEGER NOT NULL,
    tail_offset    INTEGER NOT NULL,
    tail_sha       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usage_events (
    usage_key                         TEXT PRIMARY KEY,
    source_kind                       TEXT NOT NULL,
    -- The transcript the request was read from. `session_id` is the record's own sessionId,
    -- which a subagent sidechain inherits from its parent — so it cannot say which transcript a
    -- request belongs to, and the lens counts a session per transcript. Null for legacy rows,
    -- which predate the archive and have no transcript.
    source                            TEXT,
    session_id                        TEXT,
    -- Derived once, here, so a rollup is an indexed GROUP BY rather than a full scan
    -- recomputing string surgery and date maths for every row. See `cc_session_explorer.buckets`.
    session_key                       TEXT,
    project_name                      TEXT,
    week_bucket                       TEXT,
    hour_bucket                       TEXT,
    five_min_bucket                   TEXT,
    timestamp                         TEXT,
    day                               TEXT,
    project                           TEXT,
    model                             TEXT NOT NULL,
    input_tokens                      INTEGER NOT NULL DEFAULT 0,
    output_tokens                     INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens           INTEGER NOT NULL DEFAULT 0,
    cache_creation_5m_input_tokens    INTEGER NOT NULL DEFAULT 0,
    cache_creation_1h_input_tokens    INTEGER NOT NULL DEFAULT 0,
    cache_creation_unknown_tokens     INTEGER NOT NULL DEFAULT 0,
    web_search_requests               INTEGER NOT NULL DEFAULT 0,
    web_fetch_requests                INTEGER NOT NULL DEFAULT 0,
    service_tier                      TEXT,
    speed                             TEXT,
    inference_geo                     TEXT,
    usage_json                        TEXT NOT NULL,
    cost_usd                          REAL NOT NULL DEFAULT 0,
    cost_basis                        TEXT NOT NULL,
    raw_record_count                  INTEGER NOT NULL DEFAULT 1,
    inserted_at                       TEXT NOT NULL
);

-- How far `derive_usage` has priced the records table; single-row by construction.
CREATE TABLE IF NOT EXISTS usage_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    last_record_id INTEGER NOT NULL
);

-- Per-transcript context-kind rollups, accumulated record by record as they are ingested, so the
-- ledger reads them instead of re-parsing every transcript on each request.
--
-- Keyed by `source`, not `session_id`: Claude Code gives each subagent sidechain its own file but
-- stamps it with the *parent's* sessionId, so one id can span 150+ files. Every other view here
-- calls a transcript a session, and the ledger has to count them the same way.
CREATE TABLE IF NOT EXISTS session_kinds (
    source TEXT    NOT NULL,
    kind   TEXT    NOT NULL,
    count  INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, kind)
);

CREATE TABLE IF NOT EXISTS kinds_state (
    id             INTEGER PRIMARY KEY CHECK (id = 1),
    last_record_id INTEGER NOT NULL
);

-- Raw, pre-deduplication assistant-usage totals, accumulated alongside the priced rows.
-- `usage_events` holds one row per API request, so a streaming re-echo of the same request leaves
-- no trace there; these counters are what the data view compares against to show how many
-- collapsed. Single-row by construction.
CREATE TABLE IF NOT EXISTS usage_totals (
    id                        INTEGER PRIMARY KEY CHECK (id = 1),
    assistant_usage_rows      INTEGER NOT NULL DEFAULT 0,
    raw_input_tokens          INTEGER NOT NULL DEFAULT 0,
    raw_output_tokens         INTEGER NOT NULL DEFAULT 0,
    raw_cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    raw_cache_creation_tokens INTEGER NOT NULL DEFAULT 0
);

-- Maintained rollups of usage_events: a view reads its totals instead of summing 200k rows.
-- See `cc_session_explorer.ingest.rollup` for why membership needs its own table.
CREATE TABLE IF NOT EXISTS usage_rollup (
    dimension             TEXT    NOT NULL,
    key                   TEXT    NOT NULL,
    input_tokens          INTEGER NOT NULL DEFAULT 0,
    output_tokens         INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens     INTEGER NOT NULL DEFAULT 0,
    cache_creation_tokens INTEGER NOT NULL DEFAULT 0,
    turns                 INTEGER NOT NULL DEFAULT 0,
    cost_usd              REAL    NOT NULL DEFAULT 0,
    first_seen            TEXT,
    last_seen             TEXT,
    model                 TEXT,
    PRIMARY KEY (dimension, key)
);

CREATE TABLE IF NOT EXISTS usage_rollup_sessions (
    dimension   TEXT NOT NULL,
    key         TEXT NOT NULL,
    session_key TEXT NOT NULL,
    PRIMARY KEY (dimension, key, session_key)
);

CREATE TABLE IF NOT EXISTS rollup_state (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    last_rowid INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rollup_last_seen ON usage_rollup (dimension, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_rollup_cost ON usage_rollup (dimension, cost_usd DESC);

CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_events (day);
CREATE INDEX IF NOT EXISTS idx_usage_session_key ON usage_events (session_key);
CREATE INDEX IF NOT EXISTS idx_usage_project_name ON usage_events (project_name);
CREATE INDEX IF NOT EXISTS idx_usage_week ON usage_events (week_bucket);
CREATE INDEX IF NOT EXISTS idx_usage_hour ON usage_events (hour_bucket);
CREATE INDEX IF NOT EXISTS idx_usage_five_min ON usage_events (five_min_bucket);
CREATE INDEX IF NOT EXISTS idx_usage_session ON usage_events (session_id);
CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_events (model);
CREATE INDEX IF NOT EXISTS idx_usage_project ON usage_events (project);
CREATE INDEX IF NOT EXISTS idx_usage_timestamp ON usage_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_usage_duplicate_match ON usage_events (
    source_kind,
    session_id,
    timestamp,
    model,
    input_tokens,
    output_tokens,
    cache_read_input_tokens
);
"""


def default_db_path() -> Path:
    """The store's location: ``transcripts.db`` in ``DATA_HOME``."""
    return DATA_HOME / TRANSCRIPTS_DB_NAME


class SearchHit(InputModel):
    """One full-text match: where the record lives and a highlighted snippet of the hit."""

    source: FilePath
    line_no: LineNumber
    type: str
    session_id: SessionId | None = None
    timestamp: str | None = None
    snippet: str


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the store at ``db_path``, applying the schema and owner-only permissions.

    The parent directory is created ``0700`` and the database file ``0600`` so its contents
    (which may include secrets pasted into transcripts) stay readable only by the owner.
    WAL journaling lets searches run while a long-lived writer (the watcher) ingests.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.parent.chmod(_DIR_MODE)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(_SCHEMA)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ingest_state)")}
    if "tail_offset" not in columns:
        # Pre-tail-read layout: drop the high-water marks; the next sweep re-ingests whole.
        conn.execute("DROP TABLE ingest_state")
        conn.executescript(_SCHEMA)
    db_path.chmod(_FILE_MODE)
    return conn


def count_records(conn: sqlite3.Connection) -> int:
    """Total rows in the store."""
    return int(conn.execute("SELECT count(*) FROM records").fetchone()[0])


def search(
    conn: sqlite3.Connection, query: str, limit: int = _DEFAULT_SEARCH_LIMIT
) -> list[SearchHit]:
    """Full-text search over record prose, best matches first, with a highlighted snippet.

    ``query`` is an FTS5 MATCH expression; results are ranked by relevance (``bm25``).
    """
    rows = conn.execute(
        "SELECT r.source, r.line_no, r.type, r.session_id, r.timestamp,"
        " snippet(records_fts, 0, '[', ']', '…', 12) AS snippet"
        " FROM records_fts JOIN records r ON r.id = records_fts.rowid"
        " WHERE records_fts MATCH ? ORDER BY rank LIMIT ?",
        (query, limit),
    ).fetchall()
    return [SearchHit.model_validate(dict(row)) for row in rows]


def search_readonly(
    db_path: Path, query: str, limit: int = _DEFAULT_SEARCH_LIMIT
) -> list[SearchHit]:
    """:func:`search`, but for read-facing callers (the API, the MCP server): opens the
    store read-only so a request can never create or write ``transcripts.db``, and degrades
    to no results — rather than raising — when the store doesn't exist yet or a malformed
    query is rejected by FTS5.
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return search(conn, query, limit)
    except sqlite3.DatabaseError:
        logger.warning("could not search %s (locked, corrupt, or a malformed query)", db_path)
        return []
    finally:
        conn.close()
