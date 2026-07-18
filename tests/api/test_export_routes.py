from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.api import router as explorer_router

_EXPORT = [
    {
        "uuid": "c1",
        "chat_messages": [
            {"sender": "human", "text": "ping"},
            {"sender": "assistant", "text": "pong, and then some more words to tokenize"},
        ],
    }
]


def _client(tmp_path: Path, export_path: Path | None) -> TestClient:
    app = FastAPI()
    app.state.explorer_settings = ExplorerSettings(home_dir=tmp_path, export_path=export_path)
    app.include_router(explorer_router)
    return TestClient(app)


@pytest.fixture
def export_file(tmp_path: Path) -> Path:
    path = tmp_path / "conversations.json"
    path.write_text(json.dumps(_EXPORT), encoding="utf-8")
    return path


def test_export_timeline_aggregates_configured_export(tmp_path: Path, export_file: Path) -> None:
    with _client(tmp_path, export_file) as client:
        response = client.get("/timeline/export")
    assert response.status_code == 200
    body = response.json()
    assert body["source_kind"] == "export"
    assert body["window_tokens"] == 1_000_000
    assert body["total_tokens"] > 0
    assert {event["kind"] for event in body["events"]} == {"user", "claude"}


def test_export_timeline_404_when_unconfigured(tmp_path: Path) -> None:
    with _client(tmp_path, None) as client:
        assert client.get("/timeline/export").status_code == 404


def test_export_timeline_404_when_path_missing(tmp_path: Path) -> None:
    with _client(tmp_path, tmp_path / "nope.zip") as client:
        assert client.get("/timeline/export").status_code == 404
