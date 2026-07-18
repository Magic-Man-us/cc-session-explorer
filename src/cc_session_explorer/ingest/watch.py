"""Live capture: watch ``~/.claude/projects`` and ingest transcript writes as they land.

One long-lived watcher owns the database writes. Filesystem events — filtered to
``*.jsonl`` in the Rust layer, batched and debounced by ``watchfiles`` — trigger the same
incremental ingest a manual run uses: an unchanged file costs one stat, an appended file
re-checks its boundary line and ingests its new tail, and a line torn by a mid-write read
heals on the next batch. The store is WAL-journaled, so searches run while this writes.
"""

from __future__ import annotations

import argparse
import logging
from typing import TYPE_CHECKING

from cc_session_core import DEFAULT_PROJECTS_ROOT
from watchfiles import watch

from cc_session_explorer.ingest.db import connect, default_db_path
from cc_session_explorer.ingest.ingest import ingest

if TYPE_CHECKING:
    import threading
    from pathlib import Path

    from watchfiles import Change

logger = logging.getLogger(__name__)

_DEBOUNCE_MS = 1600


def _is_transcript(_change: Change, path: str) -> bool:
    return path.endswith(".jsonl")


def watch_forever(
    db_path: Path,
    projects_root: Path = DEFAULT_PROJECTS_ROOT,
    *,
    stop_event: threading.Event | None = None,
    debounce_ms: int = _DEBOUNCE_MS,
) -> None:
    """Catch up on the current corpus, then re-ingest on every batch of transcript writes.

    Runs until ``stop_event`` is set (or forever without one). Owns its own connection —
    the single writer — so it can run on any thread.
    """
    conn = connect(db_path)
    try:
        report = ingest(conn, projects_root)
        logger.info(
            "caught up: +%d records from %d files (%d unchanged)",
            report.records_inserted,
            report.files_ingested,
            report.files_skipped,
        )
        for _changes in watch(
            projects_root,
            watch_filter=_is_transcript,
            debounce=debounce_ms,
            stop_event=stop_event,
        ):
            report = ingest(conn, projects_root)
            if report.records_inserted:
                logger.info(
                    "+%d records from %d files",
                    report.records_inserted,
                    report.files_ingested,
                )
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cc-session-watch",
        description="Watch ~/.claude/projects and ingest transcript writes live.",
    )
    parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    print(f"watching {DEFAULT_PROJECTS_ROOT} -> {default_db_path()}  (Ctrl+C stops)")
    try:
        watch_forever(default_db_path())
    except KeyboardInterrupt:
        print("stopped.")


if __name__ == "__main__":
    main()
