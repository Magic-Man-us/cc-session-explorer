"""MCP server exposing every cc-session-explorer capability as stdio tools.

A thin wrapper over the same engine functions the FastAPI ``/timeline/*`` router serves, so a
local AI (Claude Code, stdio transport) reaches the whole explorer programmatically. Roots come
from the shared :class:`ExplorerSettings` (the ``CC_SESSION_EXPLORER_*`` env vars), so behaviour
matches the API.

Register in a Claude Code ``.mcp.json``::

    {
      "mcpServers": {
        "cc-session-explorer": {
          "command": "cc-session-explorer-mcp",
          "env": {
            "CC_SESSION_EXPLORER_HOME_DIR": "/home/you",
            "CC_SESSION_EXPLORER_EXPORT_PATH": "/path/to/claude-ai-export.zip"
          }
        }
      }
    }

Run straight from a checkout with ``"command": "uv"``, ``"args": ["run", "cc-session-explorer-mcp"]``
and ``"cwd"`` set to the repo. ``CC_SESSION_EXPLORER_HOME_DIR`` defaults to the process home dir;
``CC_SESSION_EXPLORER_EXPORT_PATH`` is only needed for :func:`export_timeline`.
"""

# Tools register via the FastMCP decorator, so pyright sees them as unused.
# pyright: reportUnusedFunction=false
from __future__ import annotations

from cc_session_core import Session
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import TypeAdapter

from ..api.settings import ExplorerSettings
from ..export_timeline import load_export_timeline
from ..ingest import search_readonly
from ..models import (
    EventGroup,
    EventIndex,
    LedgerPeriod,
    ProjectLabel,
    ProjectRef,
    SessionLimit,
    SessionRef,
    SourceLabel,
    WindowTokens,
)
from ..paths import DATA_DIR_NAME
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
from ..usage.models import SearchResults
from ..viz import build_page

_SESSION_LIST: TypeAdapter[list[SessionRef]] = TypeAdapter(list[SessionRef])
_PROJECT_LIST: TypeAdapter[list[ProjectRef]] = TypeAdapter(list[ProjectRef])
_EVENT_GROUP_LIST: TypeAdapter[list[EventGroup]] = TypeAdapter(list[EventGroup])
_DEFAULT_SEARCH_LIMIT = 20

_INSTRUCTIONS = (
    "Replay Claude Code session transcripts, projects, ledgers, and Claude.ai exports as "
    "context-token timelines. Every tool returns JSON (or, for get_sankey, a self-contained HTML "
    "page). Session and project ids come from list_timeline_sessions / list_projects."
)


def build_server(settings: ExplorerSettings | None = None) -> FastMCP:
    """The stdio MCP server, its tools bound to the roots derived from `settings`.

    Args:
        settings: Explorer settings; loaded from the `CC_SESSION_EXPLORER_*` env vars when omitted.

    Returns:
        A `FastMCP` server with one tool per `/timeline/*` capability.
    """
    resolved = settings if settings is not None else ExplorerSettings()
    projects_root = resolved.home_dir / ".claude" / "projects"
    export_path = resolved.export_path
    transcripts_db = resolved.home_dir / DATA_DIR_NAME / "transcripts.db"

    server = FastMCP("cc-session-explorer", instructions=_INSTRUCTIONS)

    # Named to avoid colliding with cc-session-core's `list_sessions` tool when a client
    # runs both sibling MCP servers over the same projects root.
    @server.tool()
    def list_timeline_sessions() -> str:
        """The recorded sessions the context explorer can replay, newest first."""
        return _SESSION_LIST.dump_json(discover_sessions(projects_root)).decode()

    @server.tool()
    def list_projects() -> str:
        """The recorded projects the explorer can break down, largest first."""
        return _PROJECT_LIST.dump_json(discover_projects(projects_root)).decode()

    @server.tool()
    def get_session_timeline(session_id: SourceLabel, window: WindowTokens | None = None) -> str:
        """Replay one recorded session as a context timeline; errors when the id has no transcript."""
        path = resolve_session(projects_root, session_id)
        if path is None:
            raise ToolError("session not found")
        return from_transcript(path, window).model_dump_json()

    @server.tool()
    def get_grouped_events(session_id: SourceLabel) -> str:
        """The grouped, expandable full chain of one session — like events collapsed into
        categories, each carrying its members; errors when the id has no transcript."""
        path = resolve_session(projects_root, session_id)
        if path is None:
            raise ToolError("session not found")
        return _EVENT_GROUP_LIST.dump_json(group_events(from_transcript(path).events)).decode()

    @server.tool()
    def inspect_session_event(session_id: SourceLabel, index: EventIndex) -> str:
        """One event of a recorded session paired with the raw text it was derived from; errors
        when the id has no transcript or the index is past the end of the chain."""
        path = resolve_session(projects_root, session_id)
        if path is None:
            raise ToolError("session not found")
        inspection = inspect_event(path, index)
        if inspection is None:
            raise ToolError("event not found")
        return inspection.model_dump_json()

    @server.tool()
    def get_project_breakdown(
        project: ProjectLabel,
        window: WindowTokens | None = None,
        limit: SessionLimit | None = None,
    ) -> str:
        """Break a whole project fully down — per-kind overview + per-session summaries; errors
        when the project doesn't exist. `limit` caps how many of the largest sessions are read."""
        project_dir = resolve_project(projects_root, project)
        if project_dir is None:
            raise ToolError("project not found")
        if limit is None:
            return from_project(project_dir, window).model_dump_json()
        return from_project(project_dir, window, limit=limit).model_dump_json()

    @server.tool()
    def get_ledger(period: LedgerPeriod = LedgerPeriod.daily) -> str:
        """Daily or weekly Claude Code context-token ledger across local session transcripts."""
        return build_ledger(transcripts_db, period).model_dump_json()

    @server.tool()
    def export_timeline() -> str:
        """Aggregate the configured Claude.ai account export into one context timeline; errors
        when no export path is configured (`CC_SESSION_EXPLORER_EXPORT_PATH`) or it doesn't exist."""
        if export_path is None or not export_path.exists():
            raise ToolError("no Claude.ai export configured")
        return load_export_timeline(export_path).model_dump_json()

    @server.tool()
    def search_transcripts(query: str, limit: int = _DEFAULT_SEARCH_LIMIT) -> str:
        """Full-text search over the local transcript archive; `query` is an FTS5 MATCH
        expression. Empty results mean either no match or the watcher hasn't ingested yet."""
        hits = search_readonly(transcripts_db, query, limit)
        return SearchResults(query=query, hits=hits).model_dump_json()

    @server.tool()
    def get_sankey(session_id: SourceLabel) -> str:
        """Render one session as a self-contained Sankey token/cost-flow HTML page; errors when the
        id has no transcript."""
        path = resolve_session(projects_root, session_id)
        if path is None:
            raise ToolError("session not found")
        return build_page(Session.load(path))

    return server


def main() -> None:
    """Run the stdio MCP server (the `cc-session-explorer-mcp` console script)."""
    build_server().run()
