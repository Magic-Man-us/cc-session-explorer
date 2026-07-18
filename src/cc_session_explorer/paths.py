"""Filesystem locations for the explorer's persistent stores."""

from __future__ import annotations

import re
from pathlib import Path

DATA_DIR_NAME = ".cc-session-explorer"
DATA_HOME = Path.home() / DATA_DIR_NAME

TRANSCRIPTS_DB_NAME = "transcripts.db"

# A session id must be a clean token before it reaches a glob/path — no separators, no glob
# metacharacters — so a hostile id can neither traverse out of the projects root nor widen the
# match. UUID-style stems satisfy it.
SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9._-]+")


def resolve_session_path(projects_root: Path, session_id: str) -> Path | None:
    """Resolve a session id to its transcript path, confined to ``projects_root``.

    A session id that isn't a clean token, or that resolves outside the root, returns
    None — so a hostile id can neither traverse the filesystem nor widen the glob.
    """
    if session_id in (".", "..") or not SAFE_SESSION_ID.fullmatch(session_id):
        return None
    root = projects_root.resolve()
    for path in projects_root.glob(f"*/{session_id}.jsonl"):
        if path.is_file() and path.resolve().is_relative_to(root):
            return path
    return None
