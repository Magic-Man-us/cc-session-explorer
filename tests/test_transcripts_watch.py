"""The live watcher: WAL concurrency and event-driven incremental ingest."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from cc_session_explorer.ingest import connect, count_records
from cc_session_explorer.ingest.watch import watch_forever

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

_ASSISTANT = (
    '{"type":"assistant","uuid":"u1","sessionId":"s1","message":{"role":"assistant",'
    '"content":[{"type":"text","text":"the peregrine falcon dives"}]}}'
)
_USER = (
    '{"type":"user","uuid":"u2","sessionId":"s1",'
    '"message":{"role":"user","content":"tell me about birds"}}'
)

_DEADLINE_S = 15.0


def test_connect_enables_wal(tmp_path: Path) -> None:
    conn = connect(tmp_path / "db.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def _wait_for_count(conn: sqlite3.Connection, expected: int, deadline: float) -> None:
    while time.monotonic() < deadline:
        if count_records(conn) >= expected:
            return
        time.sleep(0.05)
    raise AssertionError(f"store never reached {expected} records")


def test_watcher_catches_up_then_ingests_live_writes(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    (root / "p").mkdir(parents=True)
    file = root / "p" / "s.jsonl"
    file.write_text(f"{_ASSISTANT}\n")  # exists before the watcher starts

    db_path = tmp_path / "transcripts.db"
    stop = threading.Event()
    watcher = threading.Thread(
        target=watch_forever,
        args=(db_path, root),
        kwargs={"stop_event": stop, "debounce_ms": 50},
        daemon=True,
    )
    watcher.start()
    reader = connect(db_path)  # WAL: reads run while the watcher writes
    try:
        deadline = time.monotonic() + _DEADLINE_S
        _wait_for_count(reader, 1, deadline)  # start-up catch-up ingested the existing line
        file.write_text(f"{_ASSISTANT}\n{_USER}\n")  # a live writer appends a turn
        _wait_for_count(reader, 2, deadline)  # the event-driven ingest picked it up
    finally:
        stop.set()
        watcher.join(timeout=_DEADLINE_S)
        reader.close()
    assert not watcher.is_alive()  # stop_event actually ends the loop
