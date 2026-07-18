from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from _transcripts import enrich_record
from _transcripts import write_transcript as _write_transcript

from cc_session_explorer.ingest.db import connect
from cc_session_explorer.ingest.ingest import ingest
from cc_session_explorer.models import ContextTimeline, EventKind, LedgerPeriod, SourceKind
from cc_session_explorer.timeline import (
    build_ledger,
    discover_sessions,
    from_transcript,
    inspect_event,
    resolve_session,
)


def test_from_transcript_maps_real_event_shapes(tmp_path: Path) -> None:
    tx = _write_transcript(
        tmp_path / "s.jsonl",
        [
            {"type": "mode", "mode": "normal"},  # metadata — contributes nothing
            {
                "type": "attachment",
                "attachment": {"type": "hook_success", "hookName": "SessionStart", "stdout": "ctx"},
            },
            {"type": "user", "message": {"role": "user", "content": "Audit the auth module"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "let me look"},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"file_path": "src/auth.ts"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x" * 400}],
                },
            },
        ],
    )
    tl = from_transcript(tx)

    assert isinstance(tl, ContextTimeline)
    assert tl.source_kind is SourceKind.session
    labels = [e.label for e in tl.events]
    assert "Hook: SessionStart" in labels
    assert "Your prompt: Audit the auth module" in labels
    assert "Read: auth.ts" in labels  # the tool_result is named from the matching tool_use
    # the 400-char result dominates and is attributed to the read, kind=claude
    read = next(e for e in tl.events if e.label == "Read: auth.ts" and e.kind is EventKind.claude)
    assert read.tokens >= 100
    assert tl.total_tokens == sum(e.tokens for e in tl.events)


def test_from_transcript_marks_subagent_turns_as_sub(tmp_path: Path) -> None:
    tx = _write_transcript(
        tmp_path / "s.jsonl",
        [{"type": "user", "isSidechain": True, "message": {"role": "user", "content": "sub task"}}],
    )
    tl = from_transcript(tx)
    assert [e.kind for e in tl.events] == [EventKind.sub]


def test_from_transcript_skips_unparseable_and_unknown_blocks(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    path.write_text(
        "not json\n"
        + json.dumps(
            enrich_record(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": [{"type": "image", "source": {}}]},
                }
            )
        )
        + "\n",
        encoding="utf-8",
    )
    tl = from_transcript(path)
    assert tl.events == []  # bad line skipped, unknown image block skipped


def _inspection_transcript(path: Path) -> Path:
    return _write_transcript(
        path,
        [
            {
                "type": "attachment",
                "attachment": {"type": "hook_success", "hookName": "SessionStart", "stdout": "ctx"},
            },
            {"type": "user", "message": {"role": "user", "content": "Audit the auth module"}},
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "thinking", "thinking": "let me look"},
                        {
                            "type": "tool_use",
                            "id": "t1",
                            "name": "Read",
                            "input": {"file_path": "src/auth.ts"},
                        },
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "RESULT BODY"}
                    ],
                },
            },
        ],
    )


def test_inspect_event_prompt_content_round_trips(tmp_path: Path) -> None:
    tx = _inspection_transcript(tmp_path / "s.jsonl")
    insp = inspect_event(tx, 1)  # 0 is the hook; 1 is the prompt
    assert insp is not None
    assert insp.event.label == "Your prompt: Audit the auth module"
    assert insp.content == "Audit the auth module"
    assert insp.content_chars == len("Audit the auth module")
    assert insp.truncated is False


def test_inspect_event_tool_result_content_is_flattened_text(tmp_path: Path) -> None:
    tx = _inspection_transcript(tmp_path / "s.jsonl")
    insp = inspect_event(tx, 3)  # hook, prompt, thinking, then the tool result
    assert insp is not None
    assert insp.event.label == "Read: auth.ts"  # named from the matching tool_use brief
    assert insp.content == "RESULT BODY"


def test_inspect_event_index_out_of_range_is_none(tmp_path: Path) -> None:
    tx = _inspection_transcript(tmp_path / "s.jsonl")
    assert inspect_event(tx, 4) is None  # exactly one past the last event
    assert inspect_event(tx, 99) is None


def test_inspect_event_caps_content_and_flags_truncation(tmp_path: Path) -> None:
    tx = _write_transcript(
        tmp_path / "s.jsonl",
        [{"type": "user", "message": {"role": "user", "content": "x" * 25_000}}],
    )
    insp = inspect_event(tx, 0)
    assert insp is not None
    assert insp.truncated is True
    assert insp.content_chars == 25_000  # the full pre-cap length
    assert len(insp.content) == 20_000  # capped for transport


def test_inspect_event_agrees_with_from_transcript_chain(tmp_path: Path) -> None:
    tx = _inspection_transcript(tmp_path / "s.jsonl")
    events = from_transcript(tx).events
    assert [(e.kind, e.label) for e in events] == [
        (EventKind.hook, "Hook: SessionStart"),
        (EventKind.user, "Your prompt: Audit the auth module"),
        (EventKind.claude, "Thinking"),
        (EventKind.claude, "Read: auth.ts"),
    ]
    for index, event in enumerate(events):
        insp = inspect_event(tx, index)
        assert insp is not None
        assert insp.event == event  # the refactored walk yields the same events, in order


def _seed_projects(root: Path) -> None:
    proj = root / "-home-user-proj"
    proj.mkdir(parents=True)
    (proj / "aaaa-1111.jsonl").write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n",
        encoding="utf-8",
    )


def test_discover_sessions_lists_transcripts(tmp_path: Path) -> None:
    _seed_projects(tmp_path)
    refs = discover_sessions(tmp_path)
    assert [r.session_id for r in refs] == ["aaaa-1111"]
    assert refs[0].project == "-home-user-proj"
    assert refs[0].size_bytes > 0


def test_discover_sessions_reports_last_modified(tmp_path: Path) -> None:
    _seed_projects(tmp_path)
    stamp = datetime(2026, 7, 2, 12, tzinfo=UTC)
    os.utime(
        tmp_path / "-home-user-proj" / "aaaa-1111.jsonl", (stamp.timestamp(), stamp.timestamp())
    )
    refs = discover_sessions(tmp_path)
    assert datetime.fromisoformat(refs[0].last_modified) == stamp


def test_discover_sessions_missing_root_is_empty(tmp_path: Path) -> None:
    assert discover_sessions(tmp_path / "nope") == []


def test_discover_sessions_skips_ids_resolve_would_reject(tmp_path: Path) -> None:
    _seed_projects(tmp_path)  # one safe id: aaaa-1111
    # a transcript whose stem isn't a safe token would always 404 on replay, so it must not list
    (tmp_path / "-home-user-proj" / "bad id.jsonl").write_text("{}\n", encoding="utf-8")
    assert [r.session_id for r in discover_sessions(tmp_path)] == ["aaaa-1111"]


def _prompt(session: str, day: str, chars: int) -> dict[str, object]:
    return {
        "type": "user",
        "uuid": f"{session}-1",
        "sessionId": session,
        "timestamp": f"{day}T12:00:00Z",
        "message": {"role": "user", "content": "x" * chars},
    }


def _ingested_store(tmp_path: Path) -> Path:
    """A store holding two sessions, on two days that share an ISO week."""
    project = tmp_path / "projects" / "-proj"
    project.mkdir(parents=True)
    _write_transcript(project / "aaaa-1111.jsonl", [_prompt("aaaa-1111", "2026-07-02", 400)])
    _write_transcript(project / "bbbb-2222.jsonl", [_prompt("bbbb-2222", "2026-07-03", 800)])

    db = tmp_path / "transcripts.db"
    conn = connect(db)
    try:
        ingest(conn, tmp_path / "projects")
    finally:
        conn.close()
    return db


def test_build_ledger_groups_sessions_by_day_and_week(tmp_path: Path) -> None:
    db = _ingested_store(tmp_path)

    daily = build_ledger(db, LedgerPeriod.daily)
    weekly = build_ledger(db, LedgerPeriod.weekly)

    assert [bucket.label for bucket in daily.buckets] == ["2026-07-03", "2026-07-02"]
    assert [bucket.session_count for bucket in daily.buckets] == [1, 1]
    assert daily.total_tokens == sum(bucket.total_tokens for bucket in daily.buckets)
    assert daily.total_tokens > 0  # the kind rollups the ingest accumulated
    assert [bucket.label for bucket in weekly.buckets] == ["2026-W27"]
    assert weekly.buckets[0].starts_on == "2026-06-29"
    assert weekly.buckets[0].ends_on == "2026-07-05"
    assert weekly.buckets[0].session_count == 2
    assert weekly.buckets[0].project_count == 1


def test_build_ledger_still_reports_a_session_whose_transcript_was_deleted(
    tmp_path: Path,
) -> None:
    """The ledger reads the store, not the corpus, so a rotated-away session stays in its bucket —
    the filesystem walk it replaces could not have seen it at all."""
    db = _ingested_store(tmp_path)
    for transcript in (tmp_path / "projects").rglob("*.jsonl"):
        transcript.unlink()

    daily = build_ledger(db, LedgerPeriod.daily)

    assert [bucket.label for bucket in daily.buckets] == ["2026-07-03", "2026-07-02"]
    assert daily.session_count == 2


def test_resolve_session_finds_real_id(tmp_path: Path) -> None:
    _seed_projects(tmp_path)
    path = resolve_session(tmp_path, "aaaa-1111")
    assert path is not None and path.name == "aaaa-1111.jsonl"


def test_resolve_session_rejects_traversal_and_glob(tmp_path: Path) -> None:
    _seed_projects(tmp_path)
    # separators, parent refs, and glob metacharacters must never resolve to a path
    for hostile in ("../../etc/passwd", "..", "a/b", "*", "aaaa-1111.jsonl"):
        assert resolve_session(tmp_path, hostile) is None
