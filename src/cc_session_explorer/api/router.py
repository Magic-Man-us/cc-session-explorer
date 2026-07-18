from __future__ import annotations

from typing import Annotated, Literal

from cc_session_core import Session, build_investigation, render_investigation_markdown
from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from cc_session_explorer.viz import SessionPage, build_page, build_page_model

from ..export_timeline import load_export_timeline
from ..models import (
    ContextTimeline,
    EventGroup,
    EventInspection,
    LedgerPeriod,
    LedgerView,
    ProjectBreakdown,
    ProjectRef,
    SessionRef,
)
from ..timeline import (
    build_ledger,
    discover_projects,
    discover_sessions,
    from_project,
    from_transcript,
    group_events,
    inspect_event,
    resolve_project,
    resolve_session,
)
from .deps import ExportPathDep, ProjectsRootDep, TranscriptsDbDep

# Window-size query param: the context window a timeline renders against. Omitted → the adapter's
# 200K default; 1_000_000 for the Opus/Sonnet 1M tiers.
WindowParam = Annotated[int | None, Query(ge=1, description="Context window to render against.")]
# Event-index path param: the zero-based position of an event in a session's arrival-ordered chain.
EventIndexParam = Annotated[int, Path(ge=0, description="Zero-based event position in the chain.")]


router = APIRouter()


@router.get("/timeline/sessions")
def list_sessions(projects_root: ProjectsRootDep) -> list[SessionRef]:
    """The recorded sessions the context explorer can replay, newest first."""
    return discover_sessions(projects_root)


@router.get("/timeline/session/{session_id}")
def session_context_timeline(
    session_id: str, projects_root: ProjectsRootDep, window_tokens: WindowParam = None
) -> ContextTimeline:
    """Replay one recorded session as a context timeline; 404 when the id has no transcript."""
    path = resolve_session(projects_root, session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    return from_transcript(path, window_tokens)


@router.get("/timeline/session/{session_id}/sankey", response_class=HTMLResponse)
def session_sankey(session_id: str, projects_root: ProjectsRootDep) -> HTMLResponse:
    """Render one session as a self-contained Sankey token/cost-flow page (via cc_session_explorer.viz)."""
    path = resolve_session(projects_root, session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    return HTMLResponse(build_page(Session.load(path)))


@router.get("/timeline/session/{session_id}/sankey-data")
def session_sankey_data(session_id: str, projects_root: ProjectsRootDep) -> SessionPage:
    """The Sankey page's stats + flow graphs as typed data, for an inline SPA embed
    (the SPA renders its own SVG rather than iframing the standalone HTML page)."""
    path = resolve_session(projects_root, session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    return build_page_model(Session.load(path))


@router.get("/timeline/session/{session_id}/investigation", response_class=PlainTextResponse)
def session_investigation(
    session_id: str, projects_root: ProjectsRootDep, fmt: Literal["markdown", "json"] = "markdown"
) -> PlainTextResponse:
    """The full investigation record for one session: every tool call with its stated
    reason, arguments, result, error, and timing, a per-tool pathway summary, and the
    complete narrative timeline; 404 when the id has no transcript."""
    path = resolve_session(projects_root, session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    report = build_investigation(Session.load(path))
    if fmt == "json":
        return PlainTextResponse(report.model_dump_json(indent=2), media_type="application/json")
    return PlainTextResponse(render_investigation_markdown(report), media_type="text/markdown")


@router.get("/timeline/session/{session_id}/grouped")
def session_grouped(session_id: str, projects_root: ProjectsRootDep) -> list[EventGroup]:
    """The grouped, expandable full chain of one session — events collapsed into categories,
    each carrying its members; 404 when the id has no transcript."""
    path = resolve_session(projects_root, session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    return group_events(from_transcript(path).events)


@router.get("/timeline/session/{session_id}/event/{index}")
def session_event(
    session_id: str, index: EventIndexParam, projects_root: ProjectsRootDep
) -> EventInspection:
    """One event of a recorded session paired with the raw text it was derived from; 404 when the
    id has no transcript or the index is past the end of the chain."""
    path = resolve_session(projects_root, session_id)
    if path is None:
        raise HTTPException(status_code=404, detail="session not found")
    inspection = inspect_event(path, index)
    if inspection is None:
        raise HTTPException(status_code=404, detail="event not found")
    return inspection


@router.get("/timeline/projects")
def list_projects(projects_root: ProjectsRootDep) -> list[ProjectRef]:
    """The recorded projects the explorer can break down, largest first."""
    return discover_projects(projects_root)


@router.get("/timeline/ledger")
def timeline_ledger(
    transcripts_db: TranscriptsDbDep,
    period: Annotated[LedgerPeriod, Query(description="Ledger grouping period.")] = (
        LedgerPeriod.daily
    ),
) -> LedgerView:
    """Daily or weekly Claude Code context-token ledger across local session transcripts."""
    return build_ledger(transcripts_db, period)


@router.get("/timeline/export")
def export_timeline(export_path: ExportPathDep) -> ContextTimeline:
    """Aggregate the configured Claude.ai account export into one context timeline. 404 when no
    export path is configured (`CC_SESSION_EXPLORER_EXPORT_PATH`) or the path does not exist."""
    if export_path is None or not export_path.exists():
        raise HTTPException(status_code=404, detail="no Claude.ai export configured")
    return load_export_timeline(export_path)


@router.get("/timeline/project/{project}")
def project_breakdown(
    project: str,
    projects_root: ProjectsRootDep,
    window_tokens: WindowParam = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> ProjectBreakdown:
    """Break a whole project fully down — per-kind overview + per-session summaries; 404 when the
    project doesn't exist. `limit` caps how many of the largest sessions are read (the adapter's
    default when omitted)."""
    project_dir = resolve_project(projects_root, project)
    if project_dir is None:
        raise HTTPException(status_code=404, detail="project not found")
    if limit is None:
        return from_project(project_dir, window_tokens)
    return from_project(project_dir, window_tokens, limit=limit)
