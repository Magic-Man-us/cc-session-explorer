from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _transcripts import write_transcript
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.api import router as explorer_router
from cc_session_explorer.ingest.db import connect
from cc_session_explorer.ingest.ingest import ingest
from cc_session_explorer.paths import DATA_DIR_NAME


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
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

    app = FastAPI()
    app.state.explorer_settings = ExplorerSettings(home_dir=tmp_path)
    app.include_router(explorer_router)
    with TestClient(app) as started:
        yield started


def test_list_sessions_includes_seeded_transcript(client: TestClient) -> None:
    body = client.get("/timeline/sessions").json()
    assert any(s["session_id"] == "sess-1" and s["project"] == "-proj" for s in body)


def test_session_timeline_replays_transcript(client: TestClient) -> None:
    response = client.get("/timeline/session/sess-1")
    assert response.status_code == 200
    body = response.json()
    assert body["source_kind"] == "session"
    assert body["source"] == "sess-1"
    assert body["total_tokens"] >= 0
    assert "Your prompt: hello there" in [e["label"] for e in body["events"]]


def test_session_timeline_unknown_id_404(client: TestClient) -> None:
    assert client.get("/timeline/session/does-not-exist").status_code == 404


def test_session_event_returns_inspection(client: TestClient) -> None:
    response = client.get("/timeline/session/sess-1/event/0")
    assert response.status_code == 200
    body = response.json()
    assert body["index"] == 0
    assert body["event"]["label"] == "Your prompt: hello there"
    assert body["content"] == "hello there"
    assert body["content_chars"] == len("hello there")
    assert body["truncated"] is False


def test_session_event_out_of_range_404(client: TestClient) -> None:
    assert client.get("/timeline/session/sess-1/event/99").status_code == 404


def test_session_event_unknown_id_404(client: TestClient) -> None:
    assert client.get("/timeline/session/does-not-exist/event/0").status_code == 404


def test_timeline_ledger_returns_daily_buckets(client: TestClient) -> None:
    response = client.get("/timeline/ledger")
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "daily"
    assert body["session_count"] == 1
    assert body["buckets"][0]["session_count"] == 1
    assert body["buckets"][0]["project_count"] == 1


def test_timeline_ledger_accepts_weekly_period(client: TestClient) -> None:
    response = client.get("/timeline/ledger?period=weekly")
    assert response.status_code == 200
    body = response.json()
    assert body["period"] == "weekly"
    assert body["buckets"][0]["label"].startswith("20")


def test_session_investigation_markdown_includes_the_transcript(client: TestClient) -> None:
    response = client.get("/timeline/session/sess-1/investigation")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "hello there" in response.text
    assert "# Investigation record" in response.text


def test_session_investigation_json_round_trips(client: TestClient) -> None:
    response = client.get("/timeline/session/sess-1/investigation?fmt=json")
    assert response.status_code == 200
    body = response.json()
    assert body["info"]["id"] == "sess-1"
    assert "tool_calls" in body and "timeline" in body


def test_session_investigation_unknown_id_404(client: TestClient) -> None:
    assert client.get("/timeline/session/does-not-exist/investigation").status_code == 404
