from __future__ import annotations

import json
from pathlib import Path

import pytest
from _transcripts import write_transcript

from cc_session_explorer.models import (
    MILLION_WINDOW_TOKENS,
    ContextEvent,
    EventKind,
    ProjectBreakdown,
)
from cc_session_explorer.timeline import (
    from_project,
    from_transcript,
    group_events,
    summarize_kinds,
)


def _events() -> list[ContextEvent]:
    return [
        ContextEvent(kind=EventKind.hook, label="Hook: SessionStart", tokens=40),
        ContextEvent(kind=EventKind.user, label="Your prompt", tokens=20),
        ContextEvent(kind=EventKind.claude, label="Read: a.py", tokens=300),
        ContextEvent(kind=EventKind.claude, label="Read: b.py", tokens=500),
        ContextEvent(kind=EventKind.claude, label="Bash: ls -la", tokens=120),
        ContextEvent(kind=EventKind.claude, label="Claude's response", tokens=60),
        ContextEvent(kind=EventKind.hook, label="Hook: PostToolUse", tokens=40),
    ]


def test_group_events_collapses_by_category_sorted_with_members() -> None:
    groups = {g.label: g for g in group_events(_events())}
    # the two reads collapse into one "Reads" group carrying both members
    assert groups["Reads"].count == 2
    assert groups["Reads"].tokens == 800
    assert [e.label for e in groups["Reads"].events] == ["Read: a.py", "Read: b.py"]
    assert groups["Bash commands"].count == 1
    assert groups["Hooks"].count == 2 and groups["Hooks"].kind is EventKind.hook
    assert groups["Your prompts"].count == 1
    # highest-token group first
    assert group_events(_events())[0].label == "Reads"


def test_group_events_handles_long_uncategorised_label() -> None:
    # an un-categorised event becomes its own group labelled by its full event label; a long one
    # (here ~120 chars) must group, not blow GroupLabel's ceiling
    long_label = "ToolSearch: select:" + ",".join(f"mcp__plugin_{i}__do_thing" for i in range(6))
    assert len(long_label) > 80
    events = [ContextEvent(kind=EventKind.claude, label=long_label, tokens=5)]
    groups = group_events(events)
    assert groups[0].label == long_label and groups[0].count == 1


def test_session_kinds_cache_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cc_session_explorer import timeline as engine

    monkeypatch.setattr(engine, "_KINDS_CACHE_MAX", 3)
    engine._KINDS_CACHE.clear()
    for i in range(6):
        path = tmp_path / f"s{i}.jsonl"
        path.write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": f"hi {i}"}}) + "\n",
            encoding="utf-8",
        )
        engine._session_kinds(path)
    assert len(engine._KINDS_CACHE) <= 3  # evicts past the cap rather than growing unbounded


def test_summarize_kinds_rolls_up_per_kind_sorted() -> None:
    kinds = {k.kind: k for k in summarize_kinds(_events())}
    assert kinds[EventKind.claude].count == 4 and kinds[EventKind.claude].tokens == 980
    assert kinds[EventKind.hook].count == 2 and kinds[EventKind.hook].tokens == 80
    assert kinds[EventKind.user].tokens == 20
    assert summarize_kinds(_events())[0].kind is EventKind.claude  # most tokens first


def _seed_project(root: Path, name: str) -> Path:
    proj = root / name
    proj.mkdir(parents=True)
    big = [
        {"type": "user", "message": {"role": "user", "content": "hello there friend"}},
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "x.py"}}
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "y" * 800}],
            },
        },
    ]
    small = [{"type": "user", "message": {"role": "user", "content": "hi"}}]
    write_transcript(proj / "bbbb-2222.jsonl", big)
    write_transcript(proj / "aaaa-1111.jsonl", small)
    return proj


def test_from_project_builds_aggregate_and_session_summaries(tmp_path: Path) -> None:
    proj = _seed_project(tmp_path, "-home-user-proj")
    pb = from_project(proj)

    assert isinstance(pb, ProjectBreakdown)
    assert pb.project == "-home-user-proj"
    assert pb.session_count == 2
    # largest transcript first
    assert pb.sessions[0].ref.session_id == "bbbb-2222"
    # the aggregate sums every session's kinds
    agg = {k.kind: k.tokens for k in pb.aggregate}
    assert agg[EventKind.claude] > 0  # the 800-char read dominates
    assert pb.total_tokens == sum(s.total_tokens for s in pb.sessions)


def test_from_project_honours_window_and_missing_dir(tmp_path: Path) -> None:
    proj = _seed_project(tmp_path, "-proj")
    pb = from_project(proj, window_tokens=MILLION_WINDOW_TOKENS)
    assert pb.window_tokens == MILLION_WINDOW_TOKENS
    assert all(s.window_tokens == MILLION_WINDOW_TOKENS for s in pb.sessions)
    # a 1M window makes a small session read as a sliver
    assert pb.sessions[0].fraction_used < 0.01

    empty = from_project(tmp_path / "nope")
    assert empty.session_count == 0 and empty.aggregate == []


def test_from_transcript_renders_against_a_million_window(tmp_path: Path) -> None:
    path = write_transcript(
        tmp_path / "s.jsonl",
        [{"type": "user", "message": {"role": "user", "content": "x" * 4000}}],
    )
    tl = from_transcript(path, window_tokens=MILLION_WINDOW_TOKENS)
    assert tl.window_tokens == MILLION_WINDOW_TOKENS
    assert 0 < tl.fraction_used < 0.01  # ~1000 tokens against 1M
