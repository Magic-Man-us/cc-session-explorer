"""A local SQLite store for Claude Code and Codex transcript records.

Records are parsed by ``cc_session_core``'s shared discriminated union; ``ingest`` loads all
configured provider roots into a SQLite database incrementally, and
``search`` runs full-text queries over it.
"""

from __future__ import annotations

from cc_session_explorer.ingest.db import (
    SearchHit,
    connect,
    count_records,
    default_db_path,
    search,
    search_readonly,
)
from cc_session_explorer.ingest.ingest import IngestReport, ingest

__all__ = [
    "IngestReport",
    "SearchHit",
    "connect",
    "count_records",
    "default_db_path",
    "ingest",
    "search",
    "search_readonly",
]
