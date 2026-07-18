"""The usage lens reads the store: turns are deduplicated once, at ingest, and outlive the file."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from cc_session_explorer.buckets import bucket_key, bucket_span
from cc_session_explorer.ingest.db import connect
from cc_session_explorer.ingest.ingest import ingest
from cc_session_explorer.usage.aggregate import (
    build_bucket,
    build_live_feed,
    build_live_sessions,
    build_snapshot,
    build_tail,
)
from cc_session_explorer.usage.scan import scan_store

if TYPE_CHECKING:
    from pathlib import Path


def _assistant_payload(
    *, uuid: str, request_id: str, message_id: str, session_id: str = "session-b"
) -> dict[str, object]:
    return {
        "type": "assistant",
        "uuid": uuid,
        "sessionId": session_id,
        "timestamp": "2026-07-03T12:00:00Z",
        "cwd": "/home/user/workplace/sample",
        "requestId": request_id,
        "message": {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": "claude-sonnet-4",
            "content": [{"type": "text", "text": "done"}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
            },
        },
    }


def _write(path: Path, payloads: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(p) for p in payloads) + "\n")


def test_one_request_across_two_transcripts_is_counted_once(tmp_path: Path) -> None:
    """A resumed or forked session logs the same API request (same requestId) into two files.
    Both reach the store, and `request_key` has to collapse them — or the request, and its cost,
    is counted twice."""
    projects_dir = tmp_path / "projects" / "-home-user-workplace-sample"
    _write(
        projects_dir / "session-a.jsonl",
        [_assistant_payload(uuid="u-a", request_id="req-shared", message_id="msg-a")],
    )
    _write(
        projects_dir / "session-b.jsonl",
        [_assistant_payload(uuid="u-b", request_id="req-shared", message_id="msg-b")],
    )

    store_db = tmp_path / "transcripts.db"
    conn = connect(store_db)
    try:
        report = ingest(conn, tmp_path / "projects")
    finally:
        conn.close()

    corpus = scan_store(store_db)
    tail = build_tail(store_db, limit=10)

    assert report.usage_priced == 1
    assert [event.key for event in tail.events] == ["req-shared"]
    assert corpus.assistant_records == 2  # both records archived...
    assert corpus.duplicate_usage_rows == 1  # ...and one of them collapsed into the other


def test_a_turn_survives_its_transcript_being_deleted(tmp_path: Path) -> None:
    """The lens reads the store, not the corpus, so a rotated-away session keeps its cost. The
    corpus walk this replaced could not see it at all."""
    projects_dir = tmp_path / "projects" / "-home-user-workplace-sample"
    transcript = projects_dir / "gone.jsonl"
    _write(
        transcript,
        [
            _assistant_payload(
                uuid="u-1", request_id="req-1", message_id="msg-1", session_id="rotated-away"
            )
        ],
    )

    store_db = tmp_path / "transcripts.db"
    conn = connect(store_db)
    try:
        ingest(conn, tmp_path / "projects")
    finally:
        conn.close()

    transcript.unlink()
    tail = build_tail(store_db, limit=10)

    assert [event.session_id for event in tail.events] == ["gone"]  # the transcript names it
    assert tail.events[0].notional_cost_usd > 0
    assert build_snapshot(store_db).totals.turns == 1


def test_bucket_keys_round_trip_through_their_span() -> None:
    """A rollup groups by a stored bucket key, and /api/bucket is later handed that key back and
    asks `bucket_span` to parse it. The two have to agree, or every drill-down comes back empty."""
    stamps = [
        datetime(2026, 7, 12, 19, 31, 12, 884000, tzinfo=UTC),  # a Sunday
        datetime(2026, 7, 6, 0, 0, 0, tzinfo=UTC),  # a Monday — the week boundary
        datetime(2026, 1, 1, 23, 59, 59, 999999, tzinfo=UTC),  # year end, last five-minute slot
        datetime(2026, 3, 2, 5, 4, 0, tzinfo=UTC),  # minute 4 rounds down to the 0 slot
    ]
    for grain in ("daily", "weekly", "hourly", "five_minute"):
        for stamp in stamps:
            key = bucket_key(grain, stamp)
            span = bucket_span(grain, key)
            assert span is not None, f"{grain} key {key!r} did not parse back"
            start, end = span
            assert start <= stamp < end, f"{grain}: {stamp} fell outside its own bucket {key}"


def test_rollups_agree_with_a_direct_aggregate(tmp_path: Path) -> None:
    """The rollups are accumulated once, as rows land, and never recomputed — so nothing else
    would notice them drifting. This is what notices: every maintained total, checked against the
    sum it claims to be."""
    projects_dir = tmp_path / "projects" / "-home-user-workplace-sample"
    _write(
        projects_dir / "one.jsonl",
        [
            _assistant_payload(uuid="u-1", request_id="r1", message_id="m1", session_id="s-1"),
            _assistant_payload(uuid="u-2", request_id="r2", message_id="m2", session_id="s-1"),
        ],
    )
    _write(
        projects_dir / "two.jsonl",
        [_assistant_payload(uuid="u-3", request_id="r3", message_id="m3", session_id="s-2")],
    )

    store_db = tmp_path / "transcripts.db"
    conn = connect(store_db)
    try:
        ingest(conn, tmp_path / "projects")
        # A second ingest must fold nothing twice — the watermark is the only thing stopping it.
        ingest(conn, tmp_path / "projects")

        for dimension, column in (
            ("total", "''"),
            ("model", "model"),
            ("project", "project_name"),
            ("session", "session_key"),
            ("day", "day"),
            ("week", "week_bucket"),
            ("hour", "hour_bucket"),
            ("five_min", "five_min_bucket"),
        ):
            truth = {
                (str(row[0]), int(row[1]), round(float(row[2]), 6), int(row[3]))
                for row in conn.execute(
                    f"SELECT {column}, SUM(input_tokens + output_tokens), SUM(cost_usd),"  # noqa: S608
                    f" COUNT(*) FROM usage_events GROUP BY {column}"
                ).fetchall()
            }
            stored = {
                (str(row[0]), int(row[1]), round(float(row[2]), 6), int(row[3]))
                for row in conn.execute(
                    "SELECT key, input_tokens + output_tokens, cost_usd, turns"
                    " FROM usage_rollup WHERE dimension = ?",
                    (dimension,),
                ).fetchall()
            }
            assert stored == truth, f"the {dimension} rollup drifted from its own sum"

        # distinct sessions, the one total a counter cannot carry
        for dimension, column in (("total", "''"), ("model", "model"), ("day", "day")):
            truth = {
                (str(row[0]), int(row[1]))
                for row in conn.execute(
                    f"SELECT {column}, COUNT(DISTINCT session_key)"  # noqa: S608
                    f" FROM usage_events GROUP BY {column}"
                ).fetchall()
            }
            stored = {
                (str(row[0]), int(row[1]))
                for row in conn.execute(
                    "SELECT key, COUNT(*) FROM usage_rollup_sessions WHERE dimension = ?"
                    " GROUP BY key",
                    (dimension,),
                ).fetchall()
            }
            assert stored == truth, f"the {dimension} session count drifted"
    finally:
        conn.close()


def test_views_serve_empty_against_a_store_that_does_not_exist(tmp_path: Path) -> None:
    """A fresh install has no store until the watcher's first ingest, and a corrupt one can be
    unreadable. Every view has to return its empty shape rather than raise — `session_rows` has no
    default, and omitting it on the empty path turned a missing store into a 500."""
    missing = tmp_path / "nothing.db"

    snapshot = build_snapshot(missing)
    assert snapshot.totals.turns == 0
    assert snapshot.recent_sessions == []

    assert build_tail(missing, limit=10).events == []

    detail = build_bucket(missing, "daily", "2026-07-12")
    assert detail is not None
    assert detail.turns == 0
    assert detail.session_rows == []

    assert build_live_sessions(missing, window_minutes=30).sessions == []


def test_live_feed_files_every_message_to_its_transcript(tmp_path: Path) -> None:
    """The unified feed spans all sessions and discriminates each record by the transcript it was
    read from — not the record's own sessionId, which a subagent sidechain inherits from its
    parent. File a sidechain by its sessionId and its messages land in the wrong session."""
    projects = tmp_path / "projects"
    # Two ordinary sessions in one project, and a subagent sidechain that carries the parent's
    # sessionId but lives in its own nested transcript.
    _write(
        projects / "-proj" / "parent.jsonl",
        [_assistant_payload(uuid="p1", request_id="rp", message_id="mp", session_id="parent")],
    )
    _write(
        projects / "-proj" / "other.jsonl",
        [_assistant_payload(uuid="o1", request_id="ro", message_id="mo", session_id="other")],
    )
    _write(
        projects / "-proj" / "parent" / "subagents" / "agent-99.jsonl",
        # sessionId is the PARENT's; the transcript is its own
        [_assistant_payload(uuid="s1", request_id="rs", message_id="ms", session_id="parent")],
    )

    store_db = tmp_path / "transcripts.db"
    conn = connect(store_db)
    try:
        ingest(conn, projects)
    finally:
        conn.close()

    feed = build_live_feed(store_db, after=0, limit=100)
    by_session: dict[str, list[str]] = {}
    for item in feed.items:
        by_session.setdefault(item.session_id, []).append(item.kind)

    # three distinct transcripts, not two sessionIds
    assert set(by_session) == {"parent", "other", "agent-99"}
    # the subagent's message filed to its own transcript, flagged, and not merged into "parent"
    subagent = next(i for i in feed.items if i.session_id == "agent-99")
    assert subagent.is_sidechain is True
    assert next(i for i in feed.items if i.session_id == "parent").is_sidechain is False


def test_live_feed_cursor_returns_only_what_is_new(tmp_path: Path) -> None:
    projects = tmp_path / "projects"
    _write(
        projects / "-proj" / "s.jsonl",
        [_assistant_payload(uuid="a1", request_id="r1", message_id="m1", session_id="s")],
    )
    store_db = tmp_path / "transcripts.db"
    conn = connect(store_db)
    try:
        ingest(conn, projects)
    finally:
        conn.close()

    first = build_live_feed(store_db, after=0, limit=100)
    assert first.items  # a fresh feed returns the backlog
    # polling from the cursor with nothing new returns empty, cursor unmoved
    caught_up = build_live_feed(store_db, after=first.cursor, limit=100)
    assert caught_up.items == []
    assert caught_up.cursor == first.cursor

    # a new message appears only past the cursor
    _write(
        projects / "-proj" / "s.jsonl",
        [
            _assistant_payload(uuid="a1", request_id="r1", message_id="m1", session_id="s"),
            _assistant_payload(uuid="a2", request_id="r2", message_id="m2", session_id="s"),
        ],
    )
    conn = connect(store_db)
    try:
        ingest(conn, projects)
    finally:
        conn.close()
    delta = build_live_feed(store_db, after=first.cursor, limit=100)
    assert [i.cursor for i in delta.items] == sorted((i.cursor for i in delta.items), reverse=True)
    assert all(i.cursor > first.cursor for i in delta.items)
