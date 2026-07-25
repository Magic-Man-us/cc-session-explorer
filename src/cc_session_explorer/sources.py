"""Provider-aware transcript discovery shared by every explorer surface."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from cc_session_core import (
    DEFAULT_CODEX_ARCHIVED_SESSIONS_ROOT,
    DEFAULT_CODEX_SESSIONS_ROOT,
    DEFAULT_PROJECTS_ROOT,
    ParseFailure,
    iter_transcript_records,
)
from cc_session_core.codex.models import SessionMetaRecord

Provider = Literal["claude", "codex"]


@dataclass(frozen=True)
class TranscriptSource:
    """One provider-owned directory containing session JSONL files."""

    provider: Provider
    root: Path
    archived: bool = False


@dataclass(frozen=True)
class TranscriptRoots:
    """All transcript locations visible to one explorer process."""

    sources: tuple[TranscriptSource, ...]

    @classmethod
    def for_home(cls, home_dir: Path) -> TranscriptRoots:
        """Build roots for a configured home while honoring core's real-process defaults."""
        home = home_dir.expanduser()
        process_home = Path.home()
        if home.resolve() == process_home.resolve():
            claude = DEFAULT_PROJECTS_ROOT
            codex = DEFAULT_CODEX_SESSIONS_ROOT
            archived = DEFAULT_CODEX_ARCHIVED_SESSIONS_ROOT
        else:
            claude = home / ".claude" / "projects"
            codex_home = home / ".codex"
            codex = codex_home / "sessions"
            archived = codex_home / "archived_sessions"
        return cls(
            (
                TranscriptSource("claude", claude),
                TranscriptSource("codex", codex),
                TranscriptSource("codex", archived, archived=True),
            )
        )

    @classmethod
    def defaults(cls) -> TranscriptRoots:
        """Build roots from cc-session-core's environment-aware defaults."""
        return cls(
            (
                TranscriptSource("claude", DEFAULT_PROJECTS_ROOT),
                TranscriptSource("codex", DEFAULT_CODEX_SESSIONS_ROOT),
                TranscriptSource("codex", DEFAULT_CODEX_ARCHIVED_SESSIONS_ROOT, archived=True),
            )
        )

    @classmethod
    def claude_only(cls, projects_root: Path) -> TranscriptRoots:
        """Compatibility adapter for callers that explicitly pass a Claude projects root."""
        return cls((TranscriptSource("claude", projects_root),))

    def files(self) -> list[tuple[TranscriptSource, Path]]:
        """Every transcript, ordered deterministically by provider root and path."""
        return sorted(
            (
                (source, path)
                for source in self.sources
                if source.root.is_dir()
                for path in source.root.rglob("*.jsonl")
                if path.is_file()
            ),
            key=lambda item: (item[0].provider, item[0].archived, str(item[1])),
        )

    def existing_directories(self) -> tuple[Path, ...]:
        """Directories that can be passed to a filesystem watcher."""
        return tuple(source.root for source in self.sources if source.root.is_dir())

    def source_for(self, path: Path) -> TranscriptSource | None:
        """The configured root containing ``path``."""
        resolved = path.resolve()
        for source in self.sources:
            if resolved.is_relative_to(source.root.resolve()):
                return source
        return None

    def storage_key(self, source: TranscriptSource, path: Path) -> str:
        """Collision-free SQLite source key across providers and active/archive roots."""
        session_id, project = source_identity(source, path)
        archive = "archived/" if source.archived else ""
        return f"{source.provider}/{archive}{project}/{session_id}.jsonl"


TranscriptLocation = TranscriptRoots | Path


def coerce_roots(location: TranscriptLocation) -> TranscriptRoots:
    """Accept the old single-Claude-root API while new callers pass all provider roots."""
    return (
        location if isinstance(location, TranscriptRoots) else TranscriptRoots.claude_only(location)
    )


def codex_identity(path: Path) -> tuple[str, str]:
    """Return a Codex session id and project label from its typed session metadata."""
    session_id = path.stem
    project = "codex"
    for record in iter_transcript_records(path):
        if isinstance(record, ParseFailure):
            continue
        if isinstance(record, SessionMetaRecord):
            session_id = str(record.payload.session_id or record.payload.id or path.stem)
            if record.payload.cwd:
                cwd = Path(str(record.payload.cwd))
                project = cwd.name or str(cwd)
            break
    return session_id, project


def source_identity(source: TranscriptSource, path: Path) -> tuple[str, str]:
    """The stable session id and human project label for one transcript."""
    if source.provider == "codex":
        return codex_identity(path)
    relative = path.relative_to(source.root)
    project = relative.parts[0] if len(relative.parts) > 1 else path.parent.name
    return path.stem, project


def source_from_environment() -> TranscriptRoots:
    """Default roots, exposed as a function so tests can safely patch the environment."""
    if "CC_SESSION_EXPLORER_HOME_DIR" in os.environ:
        return TranscriptRoots.for_home(Path(os.environ["CC_SESSION_EXPLORER_HOME_DIR"]))
    return TranscriptRoots.defaults()


def provider_from_storage_key(source: str | None) -> Provider:
    """Provider encoded in a new archive source key; legacy keys are Claude."""
    return "codex" if source and source.startswith("codex/") else "claude"


def project_from_storage_key(source: str | None) -> str | None:
    """Project segment from provider-aware or legacy archive source keys."""
    if not source:
        return None
    parts = source.split("/")
    if parts[0] not in {"claude", "codex"}:
        return parts[0]
    cursor = 1
    if cursor < len(parts) and parts[cursor] == "archived":
        cursor += 1
    return parts[cursor] if cursor < len(parts) - 1 else None
