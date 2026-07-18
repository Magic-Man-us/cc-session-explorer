from __future__ import annotations

import json
import zipfile
from pathlib import Path

from cc_session_explorer.export_timeline import from_claude_ai_export, load_export_timeline
from cc_session_explorer.models import ContextTimeline, EventKind, SourceKind

_EXPORT: list[dict[str, object]] = [
    {
        "uuid": "c1",
        "name": "First chat",
        "chat_messages": [
            {"sender": "human", "text": "how do I center a div"},
            {"sender": "assistant", "text": "Use flexbox: display flex, place items center."},
        ],
    },
    {
        "uuid": "c2",
        "name": "Second chat",
        "chat_messages": [
            # text empty → body falls back to the content blocks' text
            {
                "sender": "human",
                "text": "",
                "content": [{"type": "text", "text": "and vertically too?"}],
            },
            {"sender": "assistant", "text": "Same axis rules apply on the cross axis."},
            {"sender": "system", "text": "ignored — not a human or assistant turn"},
            {"sender": "assistant", "text": ""},  # no body → contributes nothing
        ],
    },
]


def _write_conversations(path: Path) -> Path:
    path.write_text(json.dumps(_EXPORT), encoding="utf-8")
    return path


def test_aggregates_by_sender_across_conversations(tmp_path: Path) -> None:
    timeline = from_claude_ai_export(_write_conversations(tmp_path / "conversations.json"))

    assert isinstance(timeline, ContextTimeline)
    assert timeline.source_kind is SourceKind.export
    by_kind = {event.kind: event for event in timeline.events}
    assert set(by_kind) == {EventKind.user, EventKind.claude}
    assert by_kind[EventKind.user].tokens > 0
    assert by_kind[EventKind.claude].tokens > 0
    # 2 human turns (one via content fallback) and 2 assistant turns with a body; the empty
    # assistant turn and the system sender are dropped.
    assert by_kind[EventKind.user].detail == "2 messages across 2 conversations"
    assert by_kind[EventKind.claude].detail == "2 messages across 2 conversations"


def test_reads_from_directory(tmp_path: Path) -> None:
    _write_conversations(tmp_path / "conversations.json")
    assert from_claude_ai_export(tmp_path).total_tokens > 0


def test_reads_from_zip(tmp_path: Path) -> None:
    archive = tmp_path / "export.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("conversations.json", json.dumps(_EXPORT))
    assert from_claude_ai_export(archive).total_tokens > 0


def test_empty_export_yields_no_events(tmp_path: Path) -> None:
    (tmp_path / "conversations.json").write_text("[]", encoding="utf-8")
    timeline = from_claude_ai_export(tmp_path)
    assert timeline.events == []
    assert timeline.total_tokens == 0


def test_load_export_timeline_caches_on_stat(tmp_path: Path) -> None:
    path = _write_conversations(tmp_path / "conversations.json")
    first = load_export_timeline(path)
    assert load_export_timeline(path) is first  # same stat → cached instance
