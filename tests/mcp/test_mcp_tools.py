from __future__ import annotations

from pathlib import Path
from typing import cast

import anyio
import pytest
from _transcripts import write_transcript
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import TextContent
from pydantic import JsonValue, TypeAdapter

from cc_session_explorer.api.settings import ExplorerSettings
from cc_session_explorer.ingest import connect, ingest
from cc_session_explorer.mcp import build_server
from cc_session_explorer.models import EventGroup, SessionRef
from cc_session_explorer.paths import DATA_DIR_NAME

_SESSION_LIST: TypeAdapter[list[SessionRef]] = TypeAdapter(list[SessionRef])
_GROUP_LIST: TypeAdapter[list[EventGroup]] = TypeAdapter(list[EventGroup])
# ContextTimeline/LedgerView carry computed_fields that serialize out but can't validate back into
# their extra="forbid" models, so tools emitting them are read as parsed JSON — as the route tests
# read `response.json()`.
_JSON: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


@pytest.fixture
def server(tmp_path: Path) -> FastMCP:
    projects = tmp_path / ".claude" / "projects" / "-proj"
    projects.mkdir(parents=True)
    write_transcript(
        projects / "sess-1.jsonl",
        [{"type": "user", "message": {"role": "user", "content": "hello there"}}],
    )
    # The ledger reads the store, not the corpus, so the seeded transcript has to be ingested.
    conn = connect(tmp_path / DATA_DIR_NAME / "transcripts.db")
    try:
        ingest(conn, tmp_path / ".claude" / "projects")
    finally:
        conn.close()
    return build_server(ExplorerSettings(home_dir=tmp_path))


def call(server: FastMCP, name: str, **arguments: object) -> str:
    """Invoke a tool through the real server and return its text (JSON or HTML) payload."""

    async def run() -> str:
        # call_tool's own annotation (Sequence[ContentBlock] | dict) doesn't reflect its real
        # runtime shape with convert_result=True: a (content_blocks, structured_result) pair.
        content, _ = cast(
            "tuple[list[TextContent], object]", await server.call_tool(name, arguments)
        )
        return content[0].text

    return anyio.run(run)


def test_list_timeline_sessions_includes_seeded_transcript(server: FastMCP) -> None:
    sessions = _SESSION_LIST.validate_json(call(server, "list_timeline_sessions"))
    assert any(s.session_id == "sess-1" and s.project == "-proj" for s in sessions)


def test_get_session_timeline_replays_transcript(server: FastMCP) -> None:
    timeline = _JSON.validate_json(call(server, "get_session_timeline", session_id="sess-1"))
    assert timeline["source_kind"] == "session"
    assert timeline["source"] == "sess-1"
    events = timeline["events"]
    assert isinstance(events, list)
    labels = [event["label"] for event in events if isinstance(event, dict)]
    assert "Your prompt: hello there" in labels


def test_get_grouped_events_collapses_chain(server: FastMCP) -> None:
    groups = _GROUP_LIST.validate_json(call(server, "get_grouped_events", session_id="sess-1"))
    assert "Your prompts" in [group.label for group in groups]


def test_get_ledger_returns_daily_buckets(server: FastMCP) -> None:
    ledger = _JSON.validate_json(call(server, "get_ledger"))
    assert ledger["period"] == "daily"
    assert ledger["session_count"] == 1


def test_get_sankey_returns_html(server: FastMCP) -> None:
    page = call(server, "get_sankey", session_id="sess-1")
    assert "<meta charset" in page
    assert "</script>" in page


def test_get_session_timeline_unknown_id_errors(server: FastMCP) -> None:
    with pytest.raises(ToolError, match="session not found"):
        call(server, "get_session_timeline", session_id="does-not-exist")


def test_search_transcripts_finds_ingested_prose(tmp_path: Path) -> None:
    projects = tmp_path / ".claude" / "projects" / "-proj"
    projects.mkdir(parents=True)
    write_transcript(
        projects / "sess-1.jsonl",
        [{"type": "user", "message": {"role": "user", "content": "the peregrine falcon dives"}}],
    )
    conn = connect(tmp_path / DATA_DIR_NAME / "transcripts.db")
    ingest(conn, projects_root=tmp_path / ".claude" / "projects")
    conn.commit()
    conn.close()

    server = build_server(ExplorerSettings(home_dir=tmp_path))
    results = _JSON.validate_json(call(server, "search_transcripts", query="falcon"))
    assert results["query"] == "falcon"
    hits = results["hits"]
    assert isinstance(hits, list)
    snippets = [hit["snippet"] for hit in hits if isinstance(hit, dict)]
    assert any("falcon" in str(snippet).lower() for snippet in snippets)


def test_search_transcripts_degrades_to_empty_before_any_ingest(server: FastMCP) -> None:
    # No transcripts.db exists yet (the fixture never ingests) — must not raise.
    results = _JSON.validate_json(call(server, "search_transcripts", query="anything"))
    assert results == {"query": "anything", "hits": []}
