from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.ingest import connect, ingest, search
from cc_session_explorer.models import EventKind
from cc_session_explorer.sources import TranscriptRoots
from cc_session_explorer.timeline import discover_sessions, from_transcript, resolve_session
from cc_session_explorer.usage.livelog import build_session_log
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
