from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from _transcripts import write_transcript
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.api import router as explorer_router

_BIG = [
    {"type": "user", "message": {"role": "user", "content": "audit the auth module"}},
    {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "auth.py"}}
            ],
        },
    },
    {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "z" * 600}],
        },
    },
]
_SMALL = [{"type": "user", "message": {"role": "user", "content": "hi there"}}]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    proj = tmp_path / ".claude" / "projects" / "-home-user-proj"
    proj.mkdir(parents=True)
    write_transcript(proj / "bbbb-2222.jsonl", _BIG)
    write_transcript(proj / "aaaa-1111.jsonl", _SMALL)
    app = FastAPI()
    app.state.explorer_settings = ExplorerSettings(home_dir=tmp_path)
    app.include_router(explorer_router)
    with TestClient(app) as started:
        yield started


def test_list_projects(client: TestClient) -> None:
    body = client.get("/timeline/projects").json()
    proj = next(p for p in body if p["project"] == "-home-user-proj")
    assert proj["session_count"] == 2 and proj["total_bytes"] > 0


def test_project_breakdown(client: TestClient) -> None:
    response = client.get("/timeline/project/-home-user-proj")
    assert response.status_code == 200
    body = response.json()
    assert body["session_count"] == 2
    assert body["sessions"][0]["ref"]["session_id"] == "bbbb-2222"  # largest first
    assert any(k["kind"] == "claude" for k in body["aggregate"])
    assert body["total_tokens"] == sum(s["total_tokens"] for s in body["sessions"])


def test_project_breakdown_window_and_limit(client: TestClient) -> None:
    response = client.get(
        "/timeline/project/-home-user-proj", params={"window_tokens": 1_000_000, "limit": 1}
    )
    body = response.json()
    assert body["window_tokens"] == 1_000_000
    assert body["session_count"] == 1  # capped to the 1 largest


def test_project_breakdown_unknown_404(client: TestClient) -> None:
    assert client.get("/timeline/project/-does-not-exist").status_code == 404


def test_session_grouped(client: TestClient) -> None:
    response = client.get("/timeline/session/bbbb-2222/grouped")
    assert response.status_code == 200
    groups = response.json()
    # the 600-char read collapses into a "Reads" group carrying its member event
    reads = next(g for g in groups if g["label"] == "Reads")
    assert reads["count"] == 1 and reads["kind"] == "claude" and reads["events"]


def test_session_timeline_window_param(client: TestClient) -> None:
    body = client.get("/timeline/session/bbbb-2222", params={"window_tokens": 1_000_000}).json()
    assert body["window_tokens"] == 1_000_000
    assert body["fraction_used"] < 0.01
