from __future__ import annotations

import zipfile
from functools import lru_cache
from pathlib import Path

from pydantic import TypeAdapter

from .base import InputModel
from .models import (
    MILLION_WINDOW_TOKENS,
    ContextEvent,
    ContextTimeline,
    EventKind,
    SourceKind,
)
from .tokens import count_tokens

# --- Claude.ai export boundary models -------------------------------------------------
# A Claude.ai account data export is `conversations.json`: an array of conversations, each with a
# `chat_messages` list. These are tolerant ingest shapes (InputModel drops unknown keys); only the
# sender and its text carry context, everything else (timestamps, attachments, uuids) is dropped.

_CONVERSATIONS_MEMBER = "conversations.json"

# Roll a message's sender onto the kind band the tracker colours it as. Senders outside this map
# (system notices, tool roles a future export might add) contribute nothing.
_KIND_BY_SENDER: dict[str, EventKind] = {
    "human": EventKind.user,
    "assistant": EventKind.claude,
}


class _ExportContentBlock(InputModel):
    type: str = ""
    text: str = ""


class _ExportMessage(InputModel):
    sender: str = ""
    text: str = ""
    content: list[_ExportContentBlock] = []

    def body(self) -> str:
        """The message's text — the flat `text` field, or the joined text blocks when it's empty."""
        if self.text:
            return self.text
        return "\n".join(block.text for block in self.content if block.text)


class _ExportConversation(InputModel):
    chat_messages: list[_ExportMessage] = []


_CONVERSATIONS_ADAPTER: TypeAdapter[list[_ExportConversation]] = TypeAdapter(
    list[_ExportConversation]
)


def _read_conversations_bytes(path: Path) -> bytes:
    """Read the raw `conversations.json` bytes from an export, given the zip, the extracted
    directory, or the file itself."""
    if path.is_dir():
        return (path / _CONVERSATIONS_MEMBER).read_bytes()
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            return archive.read(_CONVERSATIONS_MEMBER)
    return path.read_bytes()


def _conversation_label(count: int, messages: int) -> str:
    return f"{messages} messages across {count} conversations"


def from_claude_ai_export(path: Path) -> ContextTimeline:
    """Aggregate a whole Claude.ai account export into one context timeline.

    Every message across every conversation is tokenised with a real BPE tokenizer and summed onto
    its sender's band — human turns onto `user`, assistant turns onto `claude` — so the stacked bar
    reads as the account's total human-vs-Claude token split. Rendered against the 1M window.

    Args:
        path: The export's `conversations.json`, its extracted directory, or the downloaded zip.

    Returns:
        The aggregate timeline, source-kind `export`.
    """
    conversations = _CONVERSATIONS_ADAPTER.validate_json(_read_conversations_bytes(path))

    tokens: dict[EventKind, int] = {EventKind.user: 0, EventKind.claude: 0}
    counts: dict[EventKind, int] = {EventKind.user: 0, EventKind.claude: 0}
    for conversation in conversations:
        for message in conversation.chat_messages:
            kind = _KIND_BY_SENDER.get(message.sender)
            body = message.body() if kind is not None else ""
            if kind is None or not body:
                continue
            tokens[kind] += count_tokens(body)
            counts[kind] += 1

    total_conversations = len(conversations)
    labels = {EventKind.user: "Human turns", EventKind.claude: "Claude turns"}
    events = [
        ContextEvent(
            kind=kind,
            label=labels[kind],
            tokens=tokens[kind],
            detail=_conversation_label(total_conversations, counts[kind]),
        )
        for kind in (EventKind.user, EventKind.claude)
        if tokens[kind] > 0
    ]

    return ContextTimeline(
        source_kind=SourceKind.export,
        source="claude-ai-export",
        window_tokens=MILLION_WINDOW_TOKENS,
        events=events,
    )


@lru_cache(maxsize=4)
def _cached_timeline(path_str: str, mtime_ns: int, size: int) -> ContextTimeline:  # noqa: ARG001
    """The aggregate keyed on the export's path and stat — parsed once per distinct file version."""
    return from_claude_ai_export(Path(path_str))


def load_export_timeline(path: Path) -> ContextTimeline:
    """`from_claude_ai_export` with a stat-keyed cache, so a large export is tokenised only once
    and re-parsed only after the file changes on disk."""
    stat = path.stat()
    return _cached_timeline(str(path), stat.st_mtime_ns, stat.st_size)
