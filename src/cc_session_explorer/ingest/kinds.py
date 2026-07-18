"""Per-session context-kind rollups, accumulated as records land.

The ledger wants, per session, how many events of each kind (claude, user, hook, sub) it holds
and roughly how many context tokens they account for. Replaying every transcript to answer that
costs a full parse of the whole corpus per request; records are append-only, so instead each new
record's contribution is added to a running per-session total once, at ingest.

Token figures here are the timeline's ~4-chars-per-token estimate of context *content*, not the
API's billed usage — `usage_events` holds the real thing.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from cc_session_core import parse_line
from pydantic import ValidationError

from cc_session_explorer.timeline import record_kind_tokens

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

_UPSERT = (
    "INSERT INTO session_kinds (source, kind, count, tokens) VALUES (?, ?, ?, ?) "
    "ON CONFLICT(source, kind) DO UPDATE SET "
    "count = count + excluded.count, tokens = tokens + excluded.tokens"
)


def _watermark(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT last_record_id FROM kinds_state WHERE id = 1").fetchone()
    return int(row[0]) if row is not None else 0


def derive_kinds(conn: sqlite3.Connection) -> int:
    """Fold every record the store has gained into its session's kind rollup; return the count.

    Accumulating (rather than recomputing) is only sound because records are append-only and
    each is counted exactly once — the watermark is what guarantees it.
    """
    since = _watermark(conn)
    rows = conn.execute(
        "SELECT id, source, raw FROM records WHERE id > ? ORDER BY id", (since,)
    ).fetchall()
    totals: dict[tuple[str, str], list[int]] = {}
    highest = since
    folded = 0
    for row in rows:
        highest = int(row["id"])
        try:
            record = parse_line(row["raw"])
        except ValidationError:
            continue
        for kind, tokens in record_kind_tokens(record):
            bucket = totals.setdefault((str(row["source"]), str(kind.value)), [0, 0])
            bucket[0] += 1
            bucket[1] += tokens
            folded += 1
    conn.executemany(
        _UPSERT,
        [(source, kind, count, tokens) for (source, kind), (count, tokens) in totals.items()],
    )
    conn.execute(
        "INSERT INTO kinds_state (id, last_record_id) VALUES (1, ?)"
        " ON CONFLICT(id) DO UPDATE SET last_record_id = excluded.last_record_id",
        (highest,),
    )
    conn.commit()
    if folded:
        logger.info("rolled up %d context events", folded)
    return folded
