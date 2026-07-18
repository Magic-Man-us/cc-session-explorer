from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING

from cc_session_explorer.ingest.db import connect
from cc_session_explorer.ingest.ingest import ingest
from cc_session_explorer.ingest.usage import derive_usage, import_ccledger
from cc_session_explorer.usage.aggregate import build_tail

if TYPE_CHECKING:
    from pathlib import Path


def _write_jsonl(path: Path, payloads: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(payload) for payload in payloads) + "\n")


def _assistant_payload(
    *,
    uuid: str,
    message_id: str,
    session_id: str = "session-1",
    cache_5m: int = 0,
    cache_1h: int = 0,
) -> dict[str, object]:
    cache_total = cache_5m + cache_1h
    return {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": session_id,
        "timestamp": "2026-07-03T12:00:00Z",
        "cwd": "/home/user/workplace/sample",
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4",
            "content": [{"type": "text", "text": "done"}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 30,
                "cache_creation_input_tokens": cache_total,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": cache_5m,
                    "ephemeral_1h_input_tokens": cache_1h,
                },
            },
        },
    }


def test_ingest_dedupes_usage_events_by_request_key(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    _write_jsonl(
        projects_dir / "-home-user-workplace-sample" / "session.jsonl",
        [
            _assistant_payload(uuid="envelope-1", message_id="message-1", cache_5m=4, cache_1h=6),
            _assistant_payload(uuid="envelope-2", message_id="message-1", cache_5m=4, cache_1h=6),
        ],
    )

    conn = connect(tmp_path / "transcripts.db")
    try:
        assert ingest(conn, projects_dir).usage_priced == 1  # streaming re-echo collapses
        assert conn.execute("SELECT count(*) FROM usage_events").fetchone()[0] == 1
        row = conn.execute(
            "SELECT input_tokens, output_tokens, cache_read_input_tokens, "
            "cache_creation_5m_input_tokens, cache_creation_1h_input_tokens, "
            "cache_creation_unknown_tokens, cost_basis FROM usage_events"
        ).fetchone()
    finally:
        conn.close()

    assert row["input_tokens"] == 10
    assert row["output_tokens"] == 20
    assert row["cache_read_input_tokens"] == 30
    assert row["cache_creation_5m_input_tokens"] == 4
    assert row["cache_creation_1h_input_tokens"] == 6
    assert row["cache_creation_unknown_tokens"] == 0
    assert row["cost_basis"] == "api_list_detailed"


def test_usage_survives_the_transcript_being_deleted(tmp_path: Path) -> None:
    """Usage is priced from the record archive, not from the transcripts, so a session whose
    file has rotated out of ~/.claude/projects keeps its cost. Outliving rotation is the only
    reason the archive is kept, and deriving from disk would have thrown it away."""
    projects_dir = tmp_path / "projects"
    transcript = projects_dir / "project" / "rotated.jsonl"
    _write_jsonl(
        transcript,
        [_assistant_payload(uuid="raw-1", message_id="message-1", session_id="rotated-away")],
    )

    db = tmp_path / "transcripts.db"
    conn = connect(db)
    try:
        assert ingest(conn, projects_dir).usage_priced == 1
    finally:
        conn.close()

    transcript.unlink()

    conn = connect(db)
    try:
        # A later run over a corpus the session has vanished from must not lose its usage,
        # and must not resurrect it as a second row either.
        ingest(conn, projects_dir)
        sessions = [
            str(row[0]) for row in conn.execute("SELECT session_id FROM usage_events").fetchall()
        ]
    finally:
        conn.close()

    assert sessions == ["rotated-away"]
    assert build_tail(db, limit=1).events[0].notional_cost_usd > 0


def test_derive_usage_is_idempotent(tmp_path: Path) -> None:
    projects_dir = tmp_path / "projects"
    _write_jsonl(
        projects_dir / "project" / "session.jsonl",
        [_assistant_payload(uuid="raw-1", message_id="message-1")],
    )

    conn = connect(tmp_path / "transcripts.db")
    try:
        assert ingest(conn, projects_dir).usage_priced == 1
        assert derive_usage(conn) == 0  # nothing new to price
        assert conn.execute("SELECT count(*) FROM usage_events").fetchone()[0] == 1
    finally:
        conn.close()


def test_the_lens_degrades_to_empty_on_an_unreadable_store(tmp_path: Path) -> None:
    # A crashed ingest can leave a corrupt file, or a read-only mount can strand a hot WAL
    # unrecoverable; either way the read path must degrade, not 500 the whole dashboard.
    db = tmp_path / "transcripts.db"
    db.write_bytes(b"not a sqlite database")

    assert build_tail(db, limit=1).events == []


def test_legacy_ccledger_import_skips_raw_equivalent(tmp_path: Path) -> None:
    ccledger_path = tmp_path / "ccledger.db"
    legacy = sqlite3.connect(ccledger_path)
    try:
        legacy.execute(
            "CREATE TABLE events (uuid TEXT, ts TEXT, day TEXT, model TEXT, project TEXT, "
            "session TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, "
            "cache_creation_tokens INTEGER, source TEXT)"
        )
        legacy.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'code')",
            (
                "legacy-1",
                "2026-07-03T12:00:00Z",
                "2026-07-03",
                "claude-sonnet-4",
                "user/sample",
                "session-1",
                10,
                20,
                30,
                10,
            ),
        )
        legacy.commit()
    finally:
        legacy.close()

    projects_dir = tmp_path / "projects"
    _write_jsonl(
        projects_dir / "project" / "session.jsonl",
        [_assistant_payload(uuid="raw-1", message_id="message-1", cache_5m=4, cache_1h=6)],
    )

    conn = connect(tmp_path / "transcripts.db")
    try:
        ingest(conn, projects_dir)
        assert import_ccledger(conn, ccledger_path) == 0
        assert conn.execute("SELECT count(*) FROM usage_events").fetchone()[0] == 1
    finally:
        conn.close()


def test_legacy_import_dedupes_despite_ccledger_path_prefixed_session_ids(tmp_path: Path) -> None:
    """ccledger stores `<project-path>/<uuid>` where transcripts store the bare `<uuid>`.
    Compared literally the two never match, so the same request lands twice and the spend is
    counted twice — 50k requests and $14k of it on the machine this was found on."""
    ccledger_path = tmp_path / "ccledger.db"
    legacy = sqlite3.connect(ccledger_path)
    try:
        legacy.execute(
            "CREATE TABLE events (uuid TEXT, ts TEXT, day TEXT, model TEXT, project TEXT, "
            "session TEXT, input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, "
            "cache_creation_tokens INTEGER, source TEXT)"
        )
        legacy.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'code')",
            (
                "legacy-1",
                "2026-07-03T12:00:00Z",
                "2026-07-03",
                "claude-sonnet-4",
                "user/sample",
                "-home-user-workplace-sample/session-1",  # the same session, path-prefixed
                10,
                20,
                30,
                10,
            ),
        )
        legacy.commit()
    finally:
        legacy.close()

    projects_dir = tmp_path / "projects"
    _write_jsonl(
        projects_dir / "project" / "session.jsonl",
        [_assistant_payload(uuid="raw-1", message_id="message-1", cache_5m=4, cache_1h=6)],
    )

    conn = connect(tmp_path / "transcripts.db")
    try:
        ingest(conn, projects_dir)
        assert import_ccledger(conn, ccledger_path) == 0, "the same request was counted twice"
        assert conn.execute("SELECT count(*) FROM usage_events").fetchone()[0] == 1
    finally:
        conn.close()
