from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import Depends, Request

from cc_session_explorer.paths import DATA_DIR_NAME, TRANSCRIPTS_DB_NAME

from .settings import ExplorerSettings


def get_explorer_settings(request: Request) -> ExplorerSettings:
    """The `ExplorerSettings` stashed on `app.state` at startup, for use as a FastAPI dependency.

    Args:
        request: The incoming request, carrying the app whose `state.explorer_settings` was set
            when the router was mounted.

    Returns:
        The process-wide explorer settings.
    """
    settings = request.app.state.explorer_settings
    assert isinstance(settings, ExplorerSettings)
    return settings


def get_projects_root(request: Request) -> Path:
    """The Claude Code projects directory the session timeline routes read from.

    Args:
        request: The incoming request, carrying `state.explorer_settings` set at startup.

    Returns:
        `<home>/.claude/projects` for the configured home dir.
    """
    return get_explorer_settings(request).home_dir / ".claude" / "projects"


ProjectsRootDep = Annotated[Path, Depends(get_projects_root)]


def get_transcripts_db(request: Request) -> Path:
    """The lossless, full-text-indexed transcript archive the search route queries.

    Args:
        request: The incoming request, carrying `state.explorer_settings` set at startup.

    Returns:
        The transcripts.db path under the data dir for the configured home.
    """
    return get_explorer_settings(request).home_dir / DATA_DIR_NAME / TRANSCRIPTS_DB_NAME


TranscriptsDbDep = Annotated[Path, Depends(get_transcripts_db)]


def get_export_path(request: Request) -> Path | None:
    """The Claude.ai account export the export-timeline route aggregates, or None when unset.

    Args:
        request: The incoming request, carrying `state.explorer_settings` set at startup.

    Returns:
        The configured `export_path` (a zip, a directory, or a `conversations.json`), or None.
    """
    return get_explorer_settings(request).export_path


ExportPathDep = Annotated[Path | None, Depends(get_export_path)]
