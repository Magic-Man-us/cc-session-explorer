from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from _transcripts import write_transcript

from cc_session_explorer.models import TraceEventKind, TraceMeasurement
from cc_session_explorer.trace import build_context_trace, select_trace_window


def test_claude_trace_reconstructs_growth_compaction_and_subagents(tmp_path: Path) -> None:
    transcript = write_transcript(
        tmp_path / "claude-session.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-07-26T12:00:00Z",
                "message": {"role": "user", "content": "x" * 400},
            },
            {
                "type": "assistant",
                "timestamp": "2026-07-26T12:10:00Z",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "agent-1",
                            "name": "Agent",
                            "input": {"description": "Review the API contracts"},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "timestamp": "2026-07-26T12:15:00Z",
                "message": {"role": "user", "content": "Keep going"},
            },
            {
                "type": "system",
                "subtype": "compact_boundary",
                "timestamp": "2026-07-26T12:30:00Z",
                "content": "Conversation compacted",
                "compactMetadata": {
                    "trigger": "auto",
                    "preTokens": 1_000,
                    "postTokens": 200,
                    "durationMs": 125,
                    "messagesSummarized": 8,
                    "cumulativeDroppedTokens": 800,
                    "preservedMessages": {"uuids": ["u-1", "u-2"]},
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-07-26T12:40:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "Work resumed after compaction."}],
                },
            },
        ],
    )

    trace = build_context_trace(transcript)

    assert trace.provider == "claude"
    assert trace.compaction_count == 1
    assert trace.subagent_count == 1
    assert trace.peak_tokens == 1_000
    assert trace.final_tokens > 200

    subagent = next(event for event in trace.events if event.kind is TraceEventKind.subagent)
    assert subagent.label.startswith("Subagent spawned:")
    assert subagent.timestamp == datetime(2026, 7, 26, 12, 10, tzinfo=UTC)

    compaction = next(event for event in trace.events if event.kind is TraceEventKind.compaction)
    assert compaction.measurement is TraceMeasurement.exact
    assert compaction.context_before_tokens == 1_000
    assert compaction.context_after_tokens == 200
    assert compaction.token_delta == -800
    assert compaction.compaction is not None
    assert compaction.compaction.messages_summarized == 8
    assert compaction.compaction.preserved_items == 2


def test_selected_trace_window_is_fifteen_minutes_on_each_side(tmp_path: Path) -> None:
    transcript = write_transcript(
        tmp_path / "window.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-07-26T12:14:59Z",
                "message": {"role": "user", "content": "outside before"},
            },
            {
                "type": "user",
                "timestamp": "2026-07-26T12:15:00Z",
                "message": {"role": "user", "content": "inside before"},
            },
            {
                "type": "user",
                "timestamp": "2026-07-26T12:45:00Z",
                "message": {"role": "user", "content": "inside after"},
            },
            {
                "type": "user",
                "timestamp": "2026-07-26T12:45:01Z",
                "message": {"role": "user", "content": "outside after"},
            },
        ],
    )
    center = datetime(2026, 7, 26, 12, 30, tzinfo=UTC)

    selected = select_trace_window(build_context_trace(transcript), center, minutes=30)

    assert selected.starts_at == datetime(2026, 7, 26, 12, 15, tzinfo=UTC)
    assert selected.ends_at == datetime(2026, 7, 26, 12, 45, tzinfo=UTC)
    assert [event.label for event in selected.events] == [
        "User prompt: inside before",
        "User prompt: inside after",
    ]


def test_trace_cache_invalidates_when_transcript_grows(tmp_path: Path) -> None:
    transcript = write_transcript(
        tmp_path / "growing.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-07-26T12:00:00Z",
                "message": {"role": "user", "content": "first"},
            }
        ],
    )
    first = build_context_trace(transcript)

    appended = write_transcript(
        tmp_path / "appended.jsonl",
        [
            {
                "type": "user",
                "timestamp": "2026-07-26T12:01:00Z",
                "message": {"role": "user", "content": "second"},
            }
        ],
    ).read_text(encoding="utf-8")
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(appended)

    refreshed = build_context_trace(transcript)

    assert len(first.events) == 1
    assert [event.label for event in refreshed.events] == [
        "User prompt: first",
        "User prompt: second",
    ]


def test_codex_trace_uses_recorded_window_and_lifecycle_markers(tmp_path: Path) -> None:
    records = [
        {
            "timestamp": "2026-07-26T14:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "codex-session",
                "session_id": "codex-session",
                "cwd": "/repo",
                "base_instructions": "Follow AGENTS.md",
                "dynamic_tools": [{"name": "spawn_agent"}],
            },
        },
        {
            "timestamp": "2026-07-26T14:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "turn_started",
                "turn_id": "turn-1",
                "model_context_window": 400_000,
            },
        },
        {
            "timestamp": "2026-07-26T14:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "id": "call-item",
                "name": "spawn_agent",
                "arguments": '{"task":"inspect backend"}',
                "call_id": "call-1",
            },
        },
        {
            "timestamp": "2026-07-26T14:00:03Z",
            "type": "event_msg",
            "payload": {"type": "collab_agent_spawn_begin", "agent_id": "agent-1"},
        },
        {
            "timestamp": "2026-07-26T14:20:00Z",
            "type": "compacted",
            "payload": {
                "message": "Condensed context summary",
                "window_number": 2,
                "replacement_history": [],
            },
        },
    ]
    transcript = tmp_path / "rollout.jsonl"
    transcript.write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )

    trace = build_context_trace(transcript)

    assert trace.provider == "codex"
    assert trace.window_tokens == 400_000
    assert trace.compaction_count == 1
    assert trace.subagent_count == 2
    assert any(event.label == "Base instructions loaded" for event in trace.events)
    compaction = next(event for event in trace.events if event.kind is TraceEventKind.compaction)
    assert compaction.measurement is TraceMeasurement.estimated
    assert compaction.compaction is not None
    assert compaction.compaction.window_number == 2
