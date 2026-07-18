"""The usage lens's /api/* routes: rollups, dedup, buckets, transcripts, and block fetch."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from _transcripts import write_transcript
from fastapi.testclient import TestClient

from cc_session_explorer.api import ExplorerSettings
from cc_session_explorer.ingest import connect as connect_transcripts
from cc_session_explorer.ingest import ingest as ingest_transcript_archive
from cc_session_explorer.paths import DATA_DIR_NAME
from cc_session_explorer.webapp import create_app

_DAY = "2026-07-05"
_LONG_TEXT = "y" * 7_000  # past the 6k clip, so the event carries a ref for /api/block


def _assistant(
    request_id: str, *, minute: int, model: str, input_tokens: int, text: str = "ok"
) -> dict[str, Any]:
    return {
        "type": "assistant",
        "uuid": f"u-{request_id}",
        "requestId": request_id,
        "timestamp": f"{_DAY}T12:{minute:02d}:00Z",
        "message": {
            "role": "assistant",
            "id": f"msg-{request_id}",
            "model": model,
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": 100,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_creation": {
                    "ephemeral_1h_input_tokens": 0,
                    "ephemeral_5m_input_tokens": 0,
                },
            },
        },
    }


_SESSION_A = [
    {
        "type": "user",
        "uuid": "u-prompt",
        "timestamp": f"{_DAY}T11:59:00Z",
        "message": {"role": "user", "content": "audit the auth module"},
    },
    _assistant("r1", minute=0, model="claude-opus-4-8", input_tokens=1_000, text=_LONG_TEXT),
    _assistant("r2", minute=1, model="claude-opus-4-8", input_tokens=2_000),
]
# Session B re-echoes r2 (a resumed-session carry-over) plus one turn of its own.
_SESSION_B = [
    _assistant("r2", minute=2, model="claude-opus-4-8", input_tokens=2_000),
    _assistant("r3", minute=3, model="claude-haiku-4-5", input_tokens=4_000),
]


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    projects = tmp_path / ".claude" / "projects"
    write_transcript(
        (projects / "-home-user-alpha").mkdir(parents=True)
        or projects / "-home-user-alpha" / "aaaa-1111.jsonl",
        _SESSION_A,
    )
    write_transcript(
        (projects / "-home-user-beta").mkdir(parents=True)
        or projects / "-home-user-beta" / "bbbb-2222.jsonl",
        _SESSION_B,
    )
    # The lens reads the store, not the corpus, so the seeded transcripts have to be ingested.
    conn = connect_transcripts(tmp_path / DATA_DIR_NAME / "transcripts.db")
    try:
        ingest_transcript_archive(conn, projects)
    finally:
        conn.close()

    app = create_app(ExplorerSettings(home_dir=tmp_path))
    with TestClient(app) as test_client:
        yield test_client


def test_snapshot_dedupes_and_rolls_up(client: TestClient) -> None:
    snapshot = client.get("/api/snapshot").json()
    totals = snapshot["totals"]
    # r2's carry-over into session B is dropped: 1000+2000+4000 input, 3x100 output.
    assert totals["tokens"]["input_tokens"] == 7_000
    assert totals["tokens"]["output_tokens"] == 300
    assert totals["turns"] == 3
    assert totals["duplicate_usage_rows"] == 1
    assert totals["sessions"] == 2
    assert totals["notional_cost_usd"] > 0
    assert {m["model"] for m in snapshot["models"]} == {"claude-opus-4-8", "claude-haiku-4-5"}
    assert {p["project"] for p in snapshot["projects"]} == {"-home-user-alpha", "-home-user-beta"}
    assert [d["day"] for d in snapshot["daily"]] == [_DAY]
    sessions = {s["id"]: s for s in snapshot["recent_sessions"]}
    assert sessions["aaaa-1111"]["first_prompt"] == "audit the auth module"


def test_tail_returns_newest_first(client: TestClient) -> None:
    tail = client.get("/api/tail", params={"limit": 2}).json()
    assert [e["key"] for e in tail["events"]] == ["r3", "r2"]
    assert tail["total_cost_usd"] > 0


def test_bucket_expands_sessions(client: TestClient) -> None:
    detail = client.get("/api/bucket", params={"grain": "daily", "bucket": _DAY}).json()
    assert detail["sessions"] == 2
    assert detail["tokens"]["input_tokens"] == 7_000
    rows = {row["session_id"] for row in detail["session_rows"]}
    assert rows == {"aaaa-1111", "bbbb-2222"}


def test_bucket_unmatched_is_404(client: TestClient) -> None:
    # A valid store with no rows for this (grain, bucket) pair — unlike the missing-store case
    # (build_bucket's own test), a live store with no match 404s like every sibling lookup route.
    response = client.get("/api/bucket", params={"grain": "daily", "bucket": "2026-07-06"})
    assert response.status_code == 404


def test_session_timeline_filters_by_bucket(client: TestClient) -> None:
    timeline = client.get(
        "/api/session-timeline",
        params={"session": "aaaa-1111", "grain": "daily", "bucket": _DAY},
    ).json()
    kinds = [event["kind"] for event in timeline["events"]]
    assert kinds == ["text", "text", "text"]  # prompt + two assistant replies
    other_day = client.get(
        "/api/session-timeline",
        params={"session": "aaaa-1111", "grain": "daily", "bucket": "2026-07-06"},
    ).json()
    assert other_day["events"] == []


def test_transcript_cursor_pages_without_loss(client: TestClient) -> None:
    first = client.get("/api/session-transcript", params={"session": "aaaa-1111"}).json()
    assert len(first["events"]) == 3
    again = client.get(
        "/api/session-transcript",
        params={"session": "aaaa-1111", "after": first["cursor"]},
    ).json()
    assert again["events"] == []
    assert again["cursor"] == first["cursor"]


def test_unknown_session_is_404(client: TestClient) -> None:
    assert client.get("/api/session-transcript", params={"session": "nope"}).status_code == 404


def test_block_returns_full_clipped_text(client: TestClient) -> None:
    timeline = client.get(
        "/api/session-timeline",
        params={"session": "aaaa-1111", "grain": "daily", "bucket": _DAY},
    ).json()
    clipped = next(event for event in timeline["events"] if event["ref"] is not None)
    assert len(clipped["text"]) < len(_LONG_TEXT)
    block = client.get(
        "/api/block",
        params={
            "session": "aaaa-1111",
            "record": clipped["ref"]["record_id"],
            "index": clipped["ref"]["block_index"],
        },
    ).json()
    assert block["text"] == _LONG_TEXT


def test_spa_serves_html(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    assert index.text.lstrip().lower().startswith("<!doctype html")


def test_timeline_lens_still_mounted(client: TestClient) -> None:
    sessions = client.get("/timeline/sessions").json()
    assert {s["session_id"] for s in sessions} == {"aaaa-1111", "bbbb-2222"}


def test_snapshot_picks_up_usage_archived_after_first_request(
    client: TestClient, tmp_path: Path
) -> None:
    # First request runs with an empty archive; a later ingest must not be masked by that
    # earlier empty result (the history cache is keyed by the db's stat fingerprint).
    assert client.get("/api/snapshot").json()["totals"]["sessions"] == 2

    rotated = tmp_path / "rotated-projects" / "-home-user-gamma"
    write_transcript(
        rotated.mkdir(parents=True) or rotated / "cccc-3333.jsonl",
        [_assistant("r9", minute=5, model="claude-opus-4-8", input_tokens=8_000)],
    )
    conn = connect_transcripts(tmp_path / DATA_DIR_NAME / "transcripts.db")
    try:
        assert ingest_transcript_archive(conn, tmp_path / "rotated-projects").usage_priced == 1
    finally:
        conn.close()

    totals = client.get("/api/snapshot").json()["totals"]
    assert totals["sessions"] == 3
    assert totals["tokens"]["input_tokens"] == 15_000


def test_search_finds_ingested_prose(client: TestClient, tmp_path: Path) -> None:
    conn = connect_transcripts(tmp_path / DATA_DIR_NAME / "transcripts.db")
    ingest_transcript_archive(conn, projects_root=tmp_path / ".claude" / "projects")
    conn.commit()
    conn.close()

    results = client.get("/api/search", params={"q": "auth"}).json()
    assert results["query"] == "auth"
    assert any("aaaa-1111" in hit["source"] for hit in results["hits"])


def test_search_degrades_to_empty_before_any_ingest(client: TestClient) -> None:
    # No transcripts.db exists yet — the search route must not 500.
    results = client.get("/api/search", params={"q": "anything"}).json()
    assert results == {"query": "anything", "hits": []}
