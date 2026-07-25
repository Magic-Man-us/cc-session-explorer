"""Domain primitives for Claude Code transcript records.

The JSONL envelope is camelCase; the nested Anthropic ``message`` (and its usage and
content blocks) is snake_case.
"""

from __future__ import annotations

from typing import Annotated

from cc_session_core import types as core_types
from pydantic import Field

AgentId = core_types.AgentId
ByteSize = core_types.ByteSize
LineNumber = core_types.LineNumber
MessageId = core_types.MessageId
PrNumber = core_types.PrNumber
RecordUuid = core_types.RecordUuid
SessionId = core_types.SessionId
ToolUseId = core_types.ToolUseId

AgentTaskKey = Annotated[
    str,
    Field(min_length=1, title="Agent task key", description="Cache key for a subagent task."),
]

ProjectSlug = Annotated[
    str,
    Field(min_length=1, title="Project slug", description="The session's project/workspace slug."),
]

ModelName = Annotated[
    str,
    Field(min_length=1, title="Model name", description="Model that produced an assistant turn."),
]

RecordCount = Annotated[
    int,
    Field(ge=0, title="Record count", description="A non-negative tally of transcript records."),
]

FileCount = Annotated[
    int,
    Field(ge=0, title="File count", description="A non-negative tally of transcript files."),
]

MtimeNs = Annotated[
    int,
    Field(ge=0, title="Mtime (ns)", description="A file's modification time in nanoseconds."),
]

TailOffset = Annotated[
    int,
    Field(ge=0, title="Tail offset", description="Byte offset of a file's last ingested line."),
]

LineSha = Annotated[
    str,
    Field(
        min_length=64,
        max_length=64,
        title="Line SHA-256",
        description="Hex digest of a line's text, verifying the boundary on tail reads.",
    ),
]
