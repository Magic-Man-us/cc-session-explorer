"""/api/session-log: every record kind surfaces in full, and the cursor tails appends."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _transcripts import enrich_record, write_transcript
from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.webapp import create_app

_SESSION: list[dict[str, Any]] = [
    {
        "type": "user",
        "uuid": "u-prompt",
        "timestamp": "2026-07-05T12:00:00Z",
        "message": {"role": "user", "content": "tail my session"},
    },
    {
        "type": "assistant",
        "uuid": "u-reply",
        "requestId": "req-1",
        "timestamp": "2026-07-05T12:00:05Z",
        "message": {
            "model": "claude-opus-4-8",
            "content": [
                {"type": "thinking", "thinking": "let me look"},
                {"type": "tool_use", "id": "tu-1", "name": "Bash", "input": {"command": "ls"}},
            ],
            "usage": {
                "input_tokens": 11,
                "output_tokens": 7,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 2,
                "cache_creation": {
                    "ephemeral_1h_input_tokens": 0,
                    "ephemeral_5m_input_tokens": 0,
                },
            },
            "role": "assistant",
        },
    },
    {
        "type": "user",
        "uuid": "u-toolresult",
        "timestamp": "2026-07-05T12:00:06Z",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "tu-1", "content": "README.md"}],
        },
        "toolUseResult": {"stdout": "README.md"},
    },
    {
        "type": "system",
        "subtype": "compact_boundary",
        "content": "conversation compacted",
        "timestamp": "2026-07-05T12:01:00Z",
    },
    {
        "type": "attachment",
        "uuid": "u-hook",
        "attachment": {"type": "hook_success", "hookName": "lint", "stdout": "clean"},
    },
    {"type": "totally-new-kind", "payload": {"answer": 42}},
]


@pytest.fixture
def setup(tmp_path: Path) -> tuple[TestClient, Path]:
    project = tmp_path / ".claude" / "projects" / "-home-user-alpha"
    project.mkdir(parents=True)
    path = write_transcript(project / "cccc-3333.jsonl", _SESSION)
    app = create_app(ExplorerSettings(home_dir=tmp_path))
    return TestClient(app), path


@pytest.fixture
def client(setup: tuple[TestClient, Path]) -> Iterator[TestClient]:
    with setup[0] as test_client:
        yield test_client


def test_every_record_kind_is_surfaced(client: TestClient) -> None:
    log = client.get("/api/session-log", params={"session": "cccc-3333"}).json()
    assert [r["kind"] for r in log["records"]] == [
        "user",
        "assistant",
        "user",
        "system",
        "attachment",
        "totally-new-kind",
    ]
    assert [r["line"] for r in log["records"]] == [1, 2, 3, 4, 5, 6]
    assert log["skipped"] == 0
    assert not log["restarted"]
    assert log["offset"] > 0

    prompt, reply, result, system, hook, unknown = log["records"]
    assert prompt["blocks"] == [
        {
            "kind": "text",
            "label": None,
            "text": "tail my session",
            "is_error": False,
            "truncated": False,
            "tool_use_id": None,
        }
    ]
    assert reply["model"] == "claude-opus-4-8"
    assert reply["request_id"] == "req-1"
    assert reply["tokens"]["input_tokens"] == 11
    assert reply["tokens"]["cache_read_tokens"] == 3
    assert [b["kind"] for b in reply["blocks"]] == ["thinking", "tool_use"]
    assert reply["blocks"][1]["label"] == "Bash"
    assert "ls" in reply["blocks"][1]["text"]
    assert [b["kind"] for b in result["blocks"]] == ["tool_result", "tool_use_result"]
    # Both sides of the exchange carry the id, so the SPA can pair call and result.
    assert reply["blocks"][1]["tool_use_id"] == "tu-1"
    assert result["blocks"][0]["tool_use_id"] == "tu-1"
    assert system["summary"].startswith("compact_boundary")
    assert hook["summary"] == "hook_success"
    assert hook["blocks"][0]["kind"] == "attachment"
    assert "lint" in hook["blocks"][0]["text"]
    assert unknown["summary"] == "totally-new-kind"
    assert "42" in unknown["raw"]  # unmodeled kinds keep their full payload in raw


def test_cursor_returns_only_appended_records(setup: tuple[TestClient, Path]) -> None:
    client, path = setup
    with client:
        first = client.get("/api/session-log", params={"session": "cccc-3333"}).json()

        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    enrich_record(
                        {
                            "type": "user",
                            "uuid": "u-followup",
                            "timestamp": "2026-07-05T12:02:00Z",
                            "message": {"role": "user", "content": "and then?"},
                        }
                    )
                )
                + "\n"
            )
            fh.write("{broken\n")

        second = client.get(
            "/api/session-log",
            params={"session": "cccc-3333", "offset": first["offset"], "line": first["line"]},
        ).json()
        assert [r["kind"] for r in second["records"]] == ["user", "parse_failure"]
        assert [r["line"] for r in second["records"]] == [7, 8]
        assert second["offset"] > first["offset"]

        third = client.get(
            "/api/session-log",
            params={"session": "cccc-3333", "offset": second["offset"], "line": second["line"]},
        ).json()
        assert third["records"] == []


def test_unknown_session_is_404(client: TestClient) -> None:
    assert client.get("/api/session-log", params={"session": "nope"}).status_code == 404


_MCP_TOOL_RESULT_SESSION: list[dict[str, Any]] = [
    {
        "type": "assistant",
        "uuid": "u-call",
        "requestId": "req-mcp",
        "timestamp": "2026-07-05T12:00:00Z",
        "message": {
            "model": "claude-opus-4-8",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tu-mcp",
                    "name": "mcp__example__evaluate",
                    "input": {},
                }
            ],
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
            },
            "role": "assistant",
        },
    },
    {
        "type": "user",
        "uuid": "u-mcp-result",
        "timestamp": "2026-07-05T12:00:01Z",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "tu-mcp",
                    "content": [{"type": "text", "text": '### Result\n"{\\n  \\"ok\\": true\\n}"'}],
                }
            ],
        },
        "toolUseResult": {},
    },
]


def test_mcp_style_tool_result_content_is_not_double_wrapped(tmp_path: Path) -> None:
    project = tmp_path / ".claude" / "projects" / "-home-user-alpha"
    project.mkdir(parents=True)
    write_transcript(project / "cccc-4444.jsonl", _MCP_TOOL_RESULT_SESSION)
    app = create_app(ExplorerSettings(home_dir=tmp_path))
    with TestClient(app) as test_client:
        log = test_client.get("/api/session-log", params={"session": "cccc-4444"}).json()
    result_block = log["records"][1]["blocks"][0]
    # The block's text is the MCP item's own `text`, not the whole content list
    # re-serialized as JSON -- no leading "[" / trailing "]" / '"type":"text"' wrapper.
    assert result_block["text"] == '### Result\n"{\\n  \\"ok\\": true\\n}"'
