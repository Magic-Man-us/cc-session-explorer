from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cc_session_explorer.usage.aggregate as usage_aggregate
from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.ingest import connect, ingest, search
from cc_session_explorer.models import EventKind
from cc_session_explorer.paths import DATA_DIR_NAME
from cc_session_explorer.sources import TranscriptRoots
from cc_session_explorer.timeline import discover_sessions, from_transcript, resolve_session
from cc_session_explorer.usage.livelog import build_session_log
from cc_session_explorer.usage.scan import SessionScan
from cc_session_explorer.webapp import create_app

_SESSION_ID = "019c0000-0000-7000-8000-000000000001"


def _write_codex(path: Path, session_id: str = _SESSION_ID) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "timestamp": "2026-07-25T14:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "session_id": session_id,
                "cwd": "/work/cc-session-explorer",
                "model_provider": "openai",
            },
        },
        {
            "timestamp": "2026-07-25T14:00:00.500Z",
            "type": "turn_context",
            "payload": {"turn_id": "turn-1", "model": "gpt-5.6-codex"},
        },
        {
            "timestamp": "2026-07-25T14:00:01Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "msg-user",
                "role": "user",
                "content": [{"type": "input_text", "text": "Implement the Codex explorer."}],
            },
        },
        {
            "timestamp": "2026-07-25T14:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "reasoning",
                "id": "reason-1",
                "summary": [{"type": "summary_text", "text": "Inspect the files first."}],
            },
        },
        {
            "timestamp": "2026-07-25T14:00:03Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "id": "call-item",
                "name": "exec_command",
                "arguments": '{"cmd":"rg --files"}',
                "call_id": "call-1",
            },
        },
        {
            "timestamp": "2026-07-25T14:00:04Z",
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "id": "output-item",
                "call_id": "call-1",
                "output": "README.md\npyproject.toml",
            },
        },
        {
            "timestamp": "2026-07-25T14:00:05Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "id": "msg-final",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Implemented and validated."}],
            },
        },
        {
            "timestamp": "2026-07-25T14:00:06Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 80,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 150,
                    },
                    "last_token_usage": {
                        "input_tokens": 120,
                        "cached_input_tokens": 80,
                        "output_tokens": 30,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 150,
                    },
                    "model_context_window": 400000,
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def _write_claude(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "type": "user",
            "uuid": "claude-user",
            "sessionId": "claude-session",
            "timestamp": "2026-07-25T14:00:00Z",
            "message": {"role": "user", "content": "Inspect the Claude project."},
        },
        {
            "type": "assistant",
            "uuid": "claude-assistant",
            "requestId": "claude-request",
            "sessionId": "claude-session",
            "timestamp": "2026-07-25T14:00:01Z",
            "cwd": "/work/claude-project",
            "message": {
                "id": "claude-message",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-4-6",
                "content": [{"type": "text", "text": "Claude inspection complete."}],
                "usage": {
                    "input_tokens": 60,
                    "output_tokens": 20,
                    "cache_read_input_tokens": 10,
                    "cache_creation_input_tokens": 0,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 0,
                        "ephemeral_1h_input_tokens": 0,
                    },
                },
            },
        },
    ]
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def test_codex_discovery_and_resolution_use_shared_roots(tmp_path: Path) -> None:
    path = _write_codex(
        tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout-session.jsonl"
    )
    roots = TranscriptRoots.for_home(tmp_path)

    refs = discover_sessions(roots)

    assert [(ref.session_id, ref.project, ref.provider) for ref in refs] == [
        (_SESSION_ID, "cc-session-explorer", "codex")
    ]
    assert resolve_session(roots, _SESSION_ID) == path


def test_codex_archived_sessions_are_discovered(tmp_path: Path) -> None:
    archived_id = "019c0000-0000-7000-8000-000000000002"
    _write_codex(tmp_path / ".codex" / "archived_sessions" / "rollout-old.jsonl", archived_id)

    refs = discover_sessions(TranscriptRoots.for_home(tmp_path))

    assert [(ref.session_id, ref.provider) for ref in refs] == [(archived_id, "codex")]


def test_codex_timeline_uses_codex_event_band(tmp_path: Path) -> None:
    path = _write_codex(tmp_path / "rollout.jsonl")

    timeline = from_transcript(path)

    assert any(
        event.kind is EventKind.user and event.label.startswith("Your prompt:")
        for event in timeline.events
    )
    assert any(
        event.kind is EventKind.codex and event.label.startswith("Codex response:")
        for event in timeline.events
    )
    assert any(
        event.kind is EventKind.codex and event.label == "Thinking" for event in timeline.events
    )
    assert any(
        event.kind is EventKind.codex and event.label == "exec_command" for event in timeline.events
    )


def test_codex_ingest_is_searchable_and_keeps_session_identity(tmp_path: Path) -> None:
    _write_codex(tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout-session.jsonl")
    conn = connect(tmp_path / "transcripts.db")
    try:
        report = ingest(conn, TranscriptRoots.for_home(tmp_path))
        hits = search(conn, "Implement")
    finally:
        conn.close()

    assert report.files_total == 1
    assert report.parse_errors == 0
    assert report.usage_priced == 1
    assert len(hits) == 1
    assert hits[0].session_id == _SESSION_ID
    assert hits[0].type == "response_item"


def test_codex_live_log_uses_normalized_shared_records(tmp_path: Path) -> None:
    _write_codex(tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout-session.jsonl")

    log = build_session_log(TranscriptRoots.for_home(tmp_path), _SESSION_ID, 0, 0)

    assert log is not None
    assert log.provider == "codex"
    assert any(record.kind == "user" for record in log.records)
    assert any(
        block.kind == "text" and "Implemented and validated" in block.text
        for record in log.records
        for block in record.blocks
    )


def test_api_uses_configured_roots_for_codex(tmp_path: Path) -> None:
    _write_codex(tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout-session.jsonl")
    client = TestClient(create_app(ExplorerSettings(home_dir=tmp_path)))

    sessions = client.get("/timeline/sessions")
    timeline = client.get(f"/timeline/session/{_SESSION_ID}")

    assert sessions.status_code == 200
    assert sessions.json()[0]["provider"] == "codex"
    assert timeline.status_code == 200
    assert any(event["kind"] == "codex" for event in timeline.json()["events"])


def test_provider_scope_filters_every_provider_spanning_api(tmp_path: Path) -> None:
    _write_codex(tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout-session.jsonl")
    _write_claude(tmp_path / ".claude" / "projects" / "claude-project" / "claude-session.jsonl")
    store_db = tmp_path / DATA_DIR_NAME / "transcripts.db"
    conn = connect(store_db)
    try:
        ingest(conn, TranscriptRoots.for_home(tmp_path))
        conn.execute(
            "UPDATE usage_rollup SET last_seen = ? WHERE dimension LIKE '%session'",
            (datetime.now(UTC).isoformat(),),
        )
        conn.commit()
    finally:
        conn.close()

    client = TestClient(create_app(ExplorerSettings(home_dir=tmp_path)))

    snapshots = {
        provider: client.get("/api/snapshot", params={"provider": provider}).json()
        for provider in ("all", "claude", "codex")
    }
    assert snapshots["all"]["totals"]["turns"] == 2
    assert snapshots["all"]["totals"]["tokens"]["total_tokens"] == (
        snapshots["claude"]["totals"]["tokens"]["total_tokens"]
        + snapshots["codex"]["totals"]["tokens"]["total_tokens"]
    )
    assert snapshots["all"]["totals"]["raw_tokens"]["total_tokens"] == (
        snapshots["claude"]["totals"]["raw_tokens"]["total_tokens"]
        + snapshots["codex"]["totals"]["raw_tokens"]["total_tokens"]
    )
    assert {row["provider"] for row in snapshots["all"]["recent_sessions"]} == {
        "claude",
        "codex",
    }
    assert {row["provider"] for row in snapshots["claude"]["recent_sessions"]} == {"claude"}
    assert {row["provider"] for row in snapshots["codex"]["recent_sessions"]} == {"codex"}
    assert {row["model"] for row in snapshots["claude"]["models"]} == {"claude-sonnet-4-6"}
    assert {row["model"] for row in snapshots["codex"]["models"]} == {"gpt-5.6-codex"}

    for provider in ("claude", "codex"):
        tail = client.get("/api/tail", params={"provider": provider}).json()
        assert {row["provider"] for row in tail["events"]} == {provider}

        bucket = client.get(
            "/api/bucket",
            params={"grain": "daily", "bucket": "2026-07-25", "provider": provider},
        ).json()
        assert {row["provider"] for row in bucket["session_rows"]} == {provider}

        live = client.get(
            "/api/live-sessions",
            params={"window": 1440, "provider": provider},
        ).json()
        assert {row["provider"] for row in live["sessions"]} == {provider}

        sessions = client.get("/timeline/sessions", params={"provider": provider}).json()
        assert {row["provider"] for row in sessions} == {provider}

        projects = client.get("/timeline/projects", params={"provider": provider}).json()
        assert len(projects) == 1

        ledger = client.get("/timeline/ledger", params={"provider": provider}).json()
        assert ledger["session_count"] == 1

    codex_search = client.get("/api/search", params={"q": "Implement", "provider": "codex"}).json()
    claude_search = client.get(
        "/api/search", params={"q": "Implement", "provider": "claude"}
    ).json()
    assert len(codex_search["hits"]) == 1
    assert claude_search["hits"] == []
    assert client.get("/api/snapshot", params={"provider": "other"}).status_code == 422


def test_codex_raw_totals_do_not_mutate_the_legacy_claude_counters(tmp_path: Path) -> None:
    _write_codex(tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout.jsonl")
    _write_claude(tmp_path / ".claude" / "projects" / "claude-project" / "claude.jsonl")
    conn = connect(tmp_path / "transcripts.db")
    columns = (
        "assistant_usage_rows, raw_input_tokens, raw_output_tokens,"
        " raw_cache_read_tokens, raw_cache_creation_tokens"
    )
    try:
        ingest(conn, TranscriptRoots.for_home(tmp_path))
        legacy = tuple(conn.execute(f"SELECT {columns} FROM usage_totals WHERE id = 1").fetchone())
        claude = tuple(
            conn.execute(
                f"SELECT {columns} FROM provider_usage_totals WHERE provider = 'claude'"
            ).fetchone()
        )
        codex = tuple(
            conn.execute(
                f"SELECT {columns} FROM provider_usage_totals WHERE provider = 'codex'"
            ).fetchone()
        )
    finally:
        conn.close()

    assert legacy == claude
    assert codex[0] == 1


def test_provider_labels_use_persisted_usage_when_session_metadata_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_codex(tmp_path / ".codex" / "sessions" / "2026" / "07" / "25" / "rollout.jsonl")
    _write_claude(tmp_path / ".claude" / "projects" / "claude-project" / "claude.jsonl")
    store_db = tmp_path / "transcripts.db"
    conn = connect(store_db)
    try:
        ingest(conn, TranscriptRoots.for_home(tmp_path))
    finally:
        conn.close()

    def no_session_meta(_store_db: Path, _session_ids: list[str]) -> dict[str, SessionScan]:
        return {}

    monkeypatch.setattr(usage_aggregate, "session_meta", no_session_meta)

    both = usage_aggregate.build_snapshot(store_db)
    codex = usage_aggregate.build_snapshot(store_db, "codex")
    both_bucket = usage_aggregate.build_bucket(store_db, "daily", "2026-07-25")
    codex_bucket = usage_aggregate.build_bucket(store_db, "daily", "2026-07-25", "codex")

    assert {row.provider for row in both.recent_sessions} == {"claude", "codex"}
    assert {row.provider for row in codex.recent_sessions} == {"codex"}
    assert both_bucket is not None
    assert {row.provider for row in both_bucket.session_rows} == {"claude", "codex"}
    assert codex_bucket is not None
    assert {row.provider for row in codex_bucket.session_rows} == {"codex"}
