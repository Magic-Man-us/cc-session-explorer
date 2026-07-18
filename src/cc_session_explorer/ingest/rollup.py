"""Maintained rollups of the priced usage, so a view reads its totals instead of summing them.

Every figure the usage lens shows is a sum over ``usage_events`` grouped by one of a fixed set of
keys — model, project, session, and four time grains. Computing them per request means seven
aggregate scans of ~200k rows; accumulating them as the rows land means each view reads a handful.

Usage rows are only ever inserted (a conflicting request key is dropped, never updated), so their
``rowid`` only ever grows and a watermark over it can never skip or double-count one.

``usage_rollup_sessions`` exists because a distinct-session count is the one figure a running
total cannot carry: membership has to be remembered to be counted. It is one row per
(dimension, key, session) pair, and the count falls out of the primary key.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

# (dimension, the usage_events column carrying its key) — the single source of truth for this
# mapping; usage/aggregate.py derives its grain->column lookup from it rather than hand-copying.
DIMENSIONS: tuple[tuple[str, str], ...] = (
    ("model", "model"),
    ("project", "project_name"),
    ("session", "session_key"),
    ("day", "day"),
    ("week", "week_bucket"),
    ("hour", "hour_bucket"),
    ("five_min", "five_min_bucket"),
)
TOTAL: tuple[str, str] = ("total", "")

_UPSERT = """
INSERT INTO usage_rollup (dimension, key, input_tokens, output_tokens, cache_read_tokens,
                          cache_creation_tokens, turns, cost_usd, first_seen, last_seen, model)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(dimension, key) DO UPDATE SET
    input_tokens = input_tokens + excluded.input_tokens,
    output_tokens = output_tokens + excluded.output_tokens,
    cache_read_tokens = cache_read_tokens + excluded.cache_read_tokens,
    cache_creation_tokens = cache_creation_tokens + excluded.cache_creation_tokens,
    turns = turns + excluded.turns,
    cost_usd = cost_usd + excluded.cost_usd,
    first_seen = MIN(COALESCE(first_seen, excluded.first_seen), excluded.first_seen),
    -- the model of the latest turn, which is what a session row reports
    model = CASE
        WHEN excluded.last_seen >= COALESCE(last_seen, excluded.last_seen)
        THEN excluded.model ELSE model END,
    last_seen = MAX(COALESCE(last_seen, excluded.last_seen), excluded.last_seen)
"""

_SELECT_NEW = """
SELECT rowid, session_key, project_name, model, day, week_bucket, hour_bucket, five_min_bucket,
       timestamp, input_tokens, output_tokens, cache_read_input_tokens,
       cache_creation_5m_input_tokens + cache_creation_1h_input_tokens
           + cache_creation_unknown_tokens AS cache_creation_tokens,
       cost_usd
FROM usage_events WHERE rowid > ? ORDER BY rowid
"""


class _Bucket:
    """One (dimension, key) under construction, before it is folded into the stored total."""

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.cache_read = 0
        self.cache_creation = 0
        self.turns = 0
        self.cost = 0.0
        self.first: str | None = None
        self.last: str | None = None
        self.model: str | None = None

    def add(self, row: sqlite3.Row) -> None:
        self.input += int(row["input_tokens"] or 0)
        self.output += int(row["output_tokens"] or 0)
        self.cache_read += int(row["cache_read_input_tokens"] or 0)
        self.cache_creation += int(row["cache_creation_tokens"] or 0)
        self.turns += 1
        self.cost += float(row["cost_usd"] or 0.0)
        stamp = row["timestamp"]
        if isinstance(stamp, str) and stamp:
            self.first = stamp if self.first is None else min(self.first, stamp)
            if self.last is None or stamp >= self.last:
                self.last = stamp
                self.model = str(row["model"]) if row["model"] else None


def _watermark(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT last_rowid FROM rollup_state WHERE id = 1").fetchone()
    mark = int(row[0]) if row is not None else 0
    highest = conn.execute("SELECT COALESCE(MAX(rowid), 0) FROM usage_events").fetchone()[0]
    if mark > int(highest):
        # usage_events was rebuilt from scratch under us, so the rowids it is being compared
        # against are not the ones these totals were accumulated from. Start over rather than
        # fold new rows into stale sums.
        logger.info("usage rowids restarted; rebuilding the rollups")
        conn.execute("DELETE FROM usage_rollup")
        conn.execute("DELETE FROM usage_rollup_sessions")
        return 0
    return mark


def derive_rollups(conn: sqlite3.Connection) -> int:
    """Fold every usage row the store has gained into its rollups; return the count."""
    since = _watermark(conn)
    rows = conn.execute(_SELECT_NEW, (since,)).fetchall()
    if not rows:
        return 0

    buckets: dict[tuple[str, str], _Bucket] = {}
    members: set[tuple[str, str, str]] = set()
    highest = since
    for row in rows:
        highest = int(row["rowid"])
        session = str(row["session_key"] or "")
        pairs = [TOTAL]
        pairs.extend(
            (dimension, str(row[column]))
            for dimension, column in DIMENSIONS
            if row[column] is not None
        )
        for dimension, key in pairs:
            buckets.setdefault((dimension, key), _Bucket()).add(row)
            if session:
                members.add((dimension, key, session))

    conn.executemany(
        _UPSERT,
        [
            (
                dimension,
                key,
                acc.input,
                acc.output,
                acc.cache_read,
                acc.cache_creation,
                acc.turns,
                acc.cost,
                acc.first,
                acc.last,
                acc.model,
            )
            for (dimension, key), acc in buckets.items()
        ],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO usage_rollup_sessions (dimension, key, session_key)"
        " VALUES (?, ?, ?)",
        sorted(members),
    )
    conn.execute(
        "INSERT INTO rollup_state (id, last_rowid) VALUES (1, ?)"
        " ON CONFLICT(id) DO UPDATE SET last_rowid = excluded.last_rowid",
        (highest,),
    )
    conn.commit()
    logger.info("rolled up %d new usage events", len(rows))
    return len(rows)
