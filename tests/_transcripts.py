"""Shared test helper: write minimal synthetic transcript lines as valid cc_session_core records.

The explorer's tests describe each transcript line by only the fields that carry context — a
prompt string, a tool_use, a hook's stdout. cc_session_core validates every line against the full Claude
Code schema, so a real record also carries an envelope (sessionId/uuid/timestamp/…), an assistant
`usage`/`id`/`model` block, and a thinking-block `signature`. This helper injects that required
boilerplate around the fixture's meaningful fields, so the fixtures stay minimal and the records
still validate. Only fields a fixture omits are filled; every value a test provides is preserved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ENVELOPE: dict[str, Any] = {
    "sessionId": "sess-1",
    "uuid": "u-1",
    "parentUuid": None,
    "timestamp": "2026-07-05T12:00:00Z",
    "isSidechain": False,
    "userType": "external",
    "entrypoint": "cli",
    "cwd": "/repo",
    "gitBranch": "main",
    "version": "1.0.0",
}
_USAGE: dict[str, Any] = {
    "input_tokens": 0,
    "output_tokens": 0,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cache_creation": {"ephemeral_1h_input_tokens": 0, "ephemeral_5m_input_tokens": 0},
}
_HOOK_DEFAULTS: dict[str, Any] = {
    "command": "",
    "content": "",
    "durationMs": 0,
    "exitCode": 0,
    "hookEvent": "SessionStart",
    "stderr": "",
    "toolUseID": "hook-1",
}
_ENVELOPE_TYPES = frozenset({"user", "assistant", "attachment"})


def _enrich_block(block: dict[str, Any]) -> dict[str, Any]:
    if block.get("type") == "thinking":
        return {"signature": "sig", **block}
    if block.get("type") == "tool_use":
        return {"caller": None, **block}
    return block


def _enrich_message(message: dict[str, Any], record_type: str) -> dict[str, Any]:
    if record_type != "assistant":
        return message
    enriched = {"type": "message", "id": "msg-1", "model": "claude", "usage": _USAGE, **message}
    content = enriched.get("content")
    if isinstance(content, list):
        enriched["content"] = [_enrich_block(block) for block in content]
    return enriched


def _enrich_attachment(attachment: dict[str, Any]) -> dict[str, Any]:
    if str(attachment.get("type", "")).startswith("hook"):
        return {**_HOOK_DEFAULTS, **attachment}
    return attachment


def enrich_record(entry: dict[str, Any]) -> dict[str, Any]:
    """Wrap a minimal fixture line in the cc_session_core-required envelope/usage/signature boilerplate."""
    record_type = entry.get("type")
    if record_type not in _ENVELOPE_TYPES:
        return entry
    enriched = {**_ENVELOPE, **entry}
    message = enriched.get("message")
    if isinstance(message, dict) and isinstance(record_type, str):
        enriched["message"] = _enrich_message(message, record_type)
    attachment = enriched.get("attachment")
    if isinstance(attachment, dict):
        enriched["attachment"] = _enrich_attachment(attachment)
    return enriched


def write_transcript(path: Path, entries: list[dict[str, Any]]) -> Path:
    """Write `entries` as a `.jsonl` transcript, each line a valid cc_session_core record."""
    lines = [json.dumps(enrich_record(entry)) for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
