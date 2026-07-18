"""The usage lens's HTTP surface — the SPA's `/api/*` contract (mounted with that prefix)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from cc_session_explorer.api.deps import ProjectsRootDep, TranscriptsDbDep
from cc_session_explorer.buckets import Grain
from cc_session_explorer.usage.aggregate import (
    build_bucket,
    build_live_feed,
    build_live_sessions,
    build_search,
    build_snapshot,
    build_tail,
)
from cc_session_explorer.usage.livelog import build_session_log
from cc_session_explorer.usage.models import (
    BlockContent,
    BucketDetail,
    DashboardSnapshot,
    LiveFeed,
    LiveSessions,
    SearchResults,
    SessionLog,
    SessionTimeline,
    SessionTranscript,
    UsageTail,
)
from cc_session_explorer.usage.transcript import (
    build_block,
    build_session_timeline,
    build_transcript,
)

router = APIRouter()


@router.get("/snapshot")
def snapshot(store_db: TranscriptsDbDep) -> DashboardSnapshot:
    """Totals, rollups, and time buckets — the payload behind most dashboard views."""
    return build_snapshot(store_db)


@router.get("/tail")
def tail(
    store_db: TranscriptsDbDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 80,
) -> UsageTail:
    """The most recent usage turns, newest first."""
    return build_tail(store_db, limit)


@router.get("/bucket")
def bucket(store_db: TranscriptsDbDep, grain: Grain, bucket: str) -> BucketDetail:
    """One time bucket expanded into per-session rows."""
    detail = build_bucket(store_db, grain, bucket)
    if detail is None:
        raise HTTPException(status_code=404, detail="bucket not found")
    return detail


@router.get("/session-timeline")
def session_timeline(
    projects_root: ProjectsRootDep, session: str, grain: Grain, bucket: str
) -> SessionTimeline:
    """One session's transcript events inside one time bucket."""
    timeline = build_session_timeline(projects_root, session, grain, bucket)
    if timeline is None:
        raise HTTPException(status_code=404, detail="session not found")
    return timeline


@router.get("/live-feed")
def live_feed(
    store_db: TranscriptsDbDep,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> LiveFeed:
    """Every record ingested after the ``after`` cursor, newest first, filed to its session.

    The unified feed across all sessions; poll with the returned ``cursor`` to follow live. Drill
    into one session's full detail via ``/session-log``.
    """
    return build_live_feed(store_db, after, limit)


@router.get("/live-sessions")
def live_sessions(
    store_db: TranscriptsDbDep,
    window: Annotated[int, Query(ge=1, le=24 * 60)] = 30,
) -> LiveSessions:
    """Sessions with activity inside the trailing window, most recent first."""
    return build_live_sessions(store_db, window)


@router.get("/session-transcript")
def session_transcript(
    projects_root: ProjectsRootDep,
    session: str,
    after: Annotated[int | None, Query(ge=0)] = None,
) -> SessionTranscript:
    """The session's events past cursor ``after`` — the SPA polls this to follow live turns."""
    transcript = build_transcript(projects_root, session, after)
    if transcript is None:
        raise HTTPException(status_code=404, detail="session not found")
    return transcript


@router.get("/session-log")
def session_log(
    projects_root: ProjectsRootDep,
    session: str,
    offset: Annotated[int, Query(ge=0)] = 0,
    line: Annotated[int, Query(ge=0)] = 0,
) -> SessionLog:
    """Every record appended past the cursor, full detail — the live-log view tails this."""
    log = build_session_log(projects_root, session, offset, line)
    if log is None:
        raise HTTPException(status_code=404, detail="session not found")
    return log


@router.get("/search")
def search(
    transcripts_db: TranscriptsDbDep,
    q: Annotated[str, Query(min_length=1)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> SearchResults:
    """Full-text search over the local transcript archive; empty when the archive doesn't
    exist yet (the watcher hasn't ingested anything) or ``q`` isn't a valid FTS5 query."""
    return build_search(transcripts_db, q, limit)


@router.get("/block")
def block(
    projects_root: ProjectsRootDep,
    session: str,
    record: Annotated[int, Query(ge=0)],
    index: Annotated[int, Query(ge=0)],
) -> BlockContent:
    """The full, unclipped text of one timeline part."""
    content = build_block(projects_root, session, record, index)
    if content is None:
        raise HTTPException(status_code=404, detail="block not found")
    return content
