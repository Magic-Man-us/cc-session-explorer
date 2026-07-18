"""The time buckets the usage lens rolls up by, and the identities it groups by.

Computed once, when a usage row is written, and stored beside it — so a rollup is an indexed
GROUP BY over a column rather than a full scan recomputing string surgery for every row. It also
leaves one definition of a bucket key instead of a Python one and a SQL one to keep in step.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal

Grain = Literal["weekly", "daily", "hourly", "five_minute"]

_FIVE_MINUTES = 5


def bucket_key(grain: Grain, timestamp: datetime) -> str:
    """The key naming the bucket ``timestamp`` falls in, at ``grain``."""
    if grain == "weekly":
        return (timestamp.date() - timedelta(days=timestamp.weekday())).isoformat()
    if grain == "daily":
        return timestamp.date().isoformat()
    if grain == "hourly":
        return timestamp.replace(minute=0, second=0, microsecond=0).isoformat()
    return timestamp.replace(
        minute=timestamp.minute - timestamp.minute % _FIVE_MINUTES, second=0, microsecond=0
    ).isoformat()


def bucket_span(grain: str, bucket: str) -> tuple[datetime, datetime] | None:
    """The [start, end) window a bucket key covers, or None for an unparseable key."""
    try:
        start = datetime.fromisoformat(bucket)
    except ValueError:
        return None
    # A daily or weekly key is a bare date and parses naive; the timestamps it is compared
    # against are UTC-aware, and comparing the two raises rather than returning False.
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    spans = {
        "weekly": timedelta(days=7),
        "daily": timedelta(days=1),
        "hourly": timedelta(hours=1),
        "five_minute": timedelta(minutes=_FIVE_MINUTES),
    }
    span = spans.get(grain)
    return (start, start + span) if span else None


def session_key(source: str | None, session_id: str | None) -> str | None:
    """The session a usage row belongs to: its transcript.

    Claude Code gives a subagent sidechain its own transcript but stamps it with the *parent's*
    sessionId, so the record's own id cannot name the transcript — and every view here counts a
    session per transcript. Legacy rows have no transcript and keep the id ccledger recorded.
    """
    if source:
        return PurePosixPath(source).stem
    return session_id


def project_name(source: str | None, project: str | None) -> str | None:
    """The project a usage row belongs to: the directory holding its transcript.

    The row's own `project` comes from the record's cwd, which names the checkout rather than the
    transcript directory the rest of the app groups by.
    """
    if source:
        return source.split("/")[0]
    return project
