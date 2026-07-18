from __future__ import annotations

import logging
import sqlite3
from collections import OrderedDict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from cc_session_core import ParseFailure, iter_records, parse_tool_input, tool_result_text
from cc_session_core.models import (
    AssistantRecord,
    AttachmentRecord,
    HookAdditionalContext,
    HookBlockingError,
    HookDeferredTool,
    HookNonBlockingError,
    HookSuccess,
    HookSystemMessage,
    Record,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserRecord,
)
from cc_session_core.parsing.tools import (
    BashInput,
    DesignSyncInput,
    EditInput,
    EnterWorktreeInput,
    GlobInput,
    GrepInput,
    MonitorInput,
    ReadInput,
    ToolSearchInput,
    WebFetchInput,
    WebSearchInput,
    WriteInput,
)
from pydantic import BaseModel

from .models import (
    ContextEvent,
    ContextTimeline,
    EventGroup,
    EventInspection,
    EventKind,
    KindSummary,
    LedgerBucket,
    LedgerPeriod,
    LedgerView,
    ProjectBreakdown,
    ProjectRef,
    SessionRef,
    SessionSummary,
    SourceKind,
)
from .paths import SAFE_SESSION_ID, resolve_session_path
from .tokens import estimate_tokens

logger = logging.getLogger(__name__)


def _iso_mtime(mtime: float) -> str:
    """A transcript file's mtime as an ISO-8601 UTC timestamp, for `SessionRef.last_modified`."""
    return datetime.fromtimestamp(mtime, tz=UTC).isoformat()


# --- transcript boundary ---------------------------------------------------------------
# A Claude Code session transcript is line-delimited JSON over an evolving, external schema.
# `cc_session_core` owns that boundary: `iter_records` validates each line into the typed `Record` union
# (or a `ParseFailure` for a line it can't validate). We map each context-bearing record kind to
# the explorer's `ContextEvent`, dispatching on the typed record/block variants — no dict-poking,
# no re-validation. A tool call's short label is read off `parse_tool_input`'s typed model for the
# recognized built-in tools; MCP and other custom tools have no fixed schema to model, so those
# fall back to a raw-key scan over the untyped input dict.

_LABEL_KEYS = ("file_path", "path", "command", "pattern", "query", "url")
_LABEL_BRIEF = 48
_BASENAME_KEYS = ("file_path", "path")

# Each produced event is paired with the raw text its token estimate came from, so a single walk
# serves both the timeline (which keeps only the events) and event inspection (which keeps only the
# indexed event's text). The largest transcripts run to tens of MB, so no walk accumulates texts.
_SourcedEvent = tuple[ContextEvent, str]

# Cap the raw text carried back for inspection; `content_chars` records the full pre-cap length.
_CONTENT_CAP = 20_000


def _typed_label(model: BaseModel) -> tuple[str, bool] | None:
    """The (value, is_basename) pair for a modeled tool input's natural label field, or
    None when the tool's shape carries none of the recognized label fields."""
    match model:
        case BashInput():
            return (model.command, False)
        case ReadInput() | EditInput() | WriteInput():
            return (model.file_path, True)
        case GlobInput() | GrepInput():
            return (model.pattern, False) if model.pattern else None
        case WebFetchInput():
            return (model.url, False)
        case WebSearchInput() | ToolSearchInput():
            return (model.query, False)
        case EnterWorktreeInput():
            return (model.path, True)
        case DesignSyncInput():
            return (model.path, True) if model.path else None
        case MonitorInput():
            if model.command:
                return (model.command, False)
            if model.query:
                return (model.query, False)
            return None
        case _:
            return None


def _tool_brief(block: ToolUseBlock) -> str:
    """A short label for a tool call — its natural argument off the typed input model for a
    recognized tool, else the first recognized raw key for an MCP/custom tool, trimmed."""
    parsed = parse_tool_input(block.name, block.input)
    if isinstance(parsed, BaseModel):
        label = _typed_label(parsed)
        if label is None:
            return str(block.name)
        value, basename = label
        tail = value.rsplit("/", 1)[-1] if basename else value
        return f"{block.name}: {tail[:_LABEL_BRIEF]}"
    data = block.input
    if isinstance(data, dict):
        for key in _LABEL_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                tail = value.rsplit("/", 1)[-1] if key in _BASENAME_KEYS else value
                return f"{block.name}: {tail[:_LABEL_BRIEF]}"
    return str(block.name)


def _text_brief(text: str) -> str:
    """The first line of a prompt/response, trimmed — a chain card otherwise lists an
    undifferentiated wall of identical labels with nothing to tell entries apart at a glance."""
    first_line = text.strip().split("\n", 1)[0]
    return first_line[:_LABEL_BRIEF] + ("…" if len(first_line) > _LABEL_BRIEF else "")


def _hook_text(attachment: HookSuccess | HookNonBlockingError | HookSystemMessage) -> str:
    """The rendered text a hook attachment contributes, mirroring the old `stdout or content`."""
    match attachment:
        case HookSuccess():
            text = attachment.stdout or attachment.content
        case HookNonBlockingError():
            text = attachment.stdout or attachment.stderr
        case _:
            text = attachment.content
    return str(text)


def _attachment_events(record: AttachmentRecord) -> list[_SourcedEvent]:
    """The timeline event for a hook attachment record, with its source text. Non-hook attachments
    carry no context and contribute nothing (the old parser dropped them the same way)."""
    attachment = record.attachment
    match attachment:
        case HookSuccess() | HookNonBlockingError() | HookSystemMessage():
            text = _hook_text(attachment)
            name = attachment.hook_name
        case HookAdditionalContext() | HookDeferredTool() | HookBlockingError():
            text = ""
            name = attachment.hook_name
        case _:
            return []
    kind = EventKind.sub if record.is_sidechain else EventKind.hook
    event = ContextEvent(kind=kind, label=f"Hook: {name or 'hook'}", tokens=estimate_tokens(text))
    return [(event, text)]


def _assistant_events(record: AssistantRecord) -> list[_SourcedEvent]:
    """Timeline events for one assistant turn's content blocks, each with its source text. A
    tool_use records its id→label into no shared state here — naming happens in `_entry_events`,
    which owns the running `tool_names`."""
    base = EventKind.sub if record.is_sidechain else EventKind.claude
    events: list[_SourcedEvent] = []
    for block in record.message.content:
        match block:
            case ThinkingBlock():
                if block.thinking:
                    events.append(
                        (
                            ContextEvent(
                                kind=base, label="Thinking", tokens=estimate_tokens(block.thinking)
                            ),
                            block.thinking,
                        )
                    )
            case TextBlock():
                if block.text:
                    events.append(
                        (
                            ContextEvent(
                                kind=base,
                                label=f"Claude's response: {_text_brief(block.text)}",
                                tokens=estimate_tokens(block.text),
                            ),
                            block.text,
                        )
                    )
            case _:
                pass  # tool_use is negligible; its cost is the result, attributed on the user turn
    return events


def _record_tool_names(record: AssistantRecord, tool_names: dict[str, str]) -> None:
    """Accrue tool_use id→label from an assistant turn so a later tool_result can be named."""
    for block in record.message.content:
        if isinstance(block, ToolUseBlock) and block.id:
            tool_names[block.id] = _tool_brief(block)


def _user_events(record: UserRecord, tool_names: dict[str, str]) -> list[_SourcedEvent]:
    """Events for one user turn — a plain prompt, or the tool results it carries back — each with
    its source text."""
    content = record.message.content
    if isinstance(content, str):
        kind = EventKind.sub if record.is_sidechain else EventKind.user
        event = ContextEvent(
            kind=kind, label=f"Your prompt: {_text_brief(content)}", tokens=estimate_tokens(content)
        )
        return [(event, content)]
    base = EventKind.sub if record.is_sidechain else EventKind.claude
    events: list[_SourcedEvent] = []
    for block in content:
        if isinstance(block, ToolResultBlock):
            label = tool_names.get(block.tool_use_id, "Tool result")
            text = tool_result_text(block.content)
            events.append(
                (ContextEvent(kind=base, label=label, tokens=estimate_tokens(text)), text)
            )
    return events


def _record_events(
    record: Record | ParseFailure, tool_names: dict[str, str]
) -> list[_SourcedEvent]:
    """Events one transcript record contributes, each with its source text; `tool_names` accrues
    tool_use id→label so a later tool_result can be named. Non-context records (session metadata,
    unknown kinds) and unparseable lines contribute nothing."""
    match record:
        case AttachmentRecord():
            return _attachment_events(record)
        case UserRecord():
            return _user_events(record, tool_names)
        case AssistantRecord():
            _record_tool_names(record, tool_names)
            return _assistant_events(record)
        case _:
            return []


def record_kind_tokens(record: Record | ParseFailure) -> list[tuple[EventKind, int]]:
    """The (kind, tokens) each event of one record contributes, in isolation.

    Only an event's *label* needs the running tool_use id→name state a full replay carries; its
    kind and token estimate come from the record alone. So a rollup can accumulate record by
    record — which is what lets the ledger be maintained at ingest instead of replaying every
    transcript per request.
    """
    return [(event.kind, event.tokens) for event, _ in _record_events(record, {})]


def from_transcript(path: Path, window_tokens: int | None = None) -> ContextTimeline:
    """Replay a real Claude Code session transcript as a context timeline.

    Tokens are estimated from each event's own text (≈4 chars/token); the transcript's real
    `usage` blocks aren't required for the shape and are reserved for a later calibration pass.

    Args:
        path: Path to a session `.jsonl` transcript.
        window_tokens: Context window to render against; the model default when omitted.

    Returns:
        The timeline, source-kind `session`, labelled with the file stem.
    """
    tool_names: dict[str, str] = {}
    events: list[ContextEvent] = []
    for record in iter_records(path):  # stream — transcripts can run to tens of MB
        events.extend(event for event, _ in _record_events(record, tool_names))

    return ContextTimeline(
        source_kind=SourceKind.session,
        source=path.stem,
        events=events,
        **({"window_tokens": window_tokens} if window_tokens else {}),
    )


def inspect_event(path: Path, index: int) -> EventInspection | None:
    """The event at `index` in a replayed session, paired with the raw text it was derived from.

    Walks the transcript exactly as `from_transcript` does, holding only the running index and the
    matched event's source text — never every text. The text is capped at `_CONTENT_CAP`;
    `content_chars` records the full pre-cap length and `truncated` says whether the cap bit.

    Args:
        path: Path to a session `.jsonl` transcript.
        index: Zero-based position of the event in the timeline's arrival-ordered chain.

    Returns:
        The inspection, or None when `index` is past the end of the chain.
    """
    tool_names: dict[str, str] = {}
    cursor = 0
    for record in iter_records(path):  # stream — transcripts can run to tens of MB
        for event, text in _record_events(record, tool_names):  # one record yields many events
            if cursor == index:
                return EventInspection(
                    index=index,
                    event=event,
                    content=text[:_CONTENT_CAP],
                    content_chars=len(text),
                    truncated=len(text) > _CONTENT_CAP,
                )
            cursor += 1
    return None


def discover_sessions(projects_root: Path) -> list[SessionRef]:
    """List session transcripts under a Claude Code projects root, newest first.

    Args:
        projects_root: The `~/.claude/projects` directory holding `<project>/<id>.jsonl` files.

    Returns:
        One ref per transcript, most-recently-modified first; `[]` if the root is absent.
    """
    if not projects_root.is_dir():
        return []
    found: list[tuple[float, SessionRef]] = []
    for path in projects_root.glob("*/*.jsonl"):
        # only list ids resolve_session will accept, so the UI never offers an always-404 session
        if not path.is_file() or not SAFE_SESSION_ID.fullmatch(path.stem):
            continue
        stat = path.stat()
        ref = SessionRef(
            session_id=path.stem,
            project=path.parent.name,
            size_bytes=stat.st_size,
            last_modified=_iso_mtime(stat.st_mtime),
        )
        found.append((stat.st_mtime, ref))
    return [ref for _, ref in sorted(found, key=lambda item: item[0], reverse=True)]


def resolve_session(projects_root: Path, session_id: str) -> Path | None:
    """Resolve a session id to its transcript path, confined to `projects_root`.

    A session id that isn't a clean token, or that resolves outside the root, returns None —
    so a hostile id can neither traverse the filesystem nor widen the glob.

    Args:
        projects_root: The projects directory to search.
        session_id: The bare transcript stem to resolve.

    Returns:
        The transcript path, or None when no safe match exists.
    """
    return resolve_session_path(projects_root, session_id)


# --- grouping + project breakdown -----------------------------------------------------
# The grouped, expandable full-chain view collapses like events into a category (all the reads,
# all the hooks); the project breakdown rolls every session up by kind for an overview, with a
# per-session summary for the drill-down list.
_CATEGORY_BY_PREFIX = {
    "Read": "Reads",
    "Bash": "Bash commands",
    "Write": "Writes",
    "Edit": "Edits",
    "Grep": "Greps",
    "Glob": "Globs",
}


def _category(event: ContextEvent) -> str:
    """The collapse category for an event: a tool family, hooks, prompts, responses, or — for
    the auto-loaded band, where each item is distinct — its own label."""
    head = event.label.split(":", 1)[0] if ":" in event.label else event.label
    if head.startswith("mcp__"):
        return "MCP results"
    if head == "Hook":
        return "Hooks"
    if head in _CATEGORY_BY_PREFIX:
        return _CATEGORY_BY_PREFIX[head]
    if head == "Your prompt":
        return "Your prompts"
    if head == "Claude's response":
        return "Responses"
    return event.label


def group_events(events: list[ContextEvent]) -> list[EventGroup]:
    """Collapse events into categories for the grouped, expandable full-chain view, highest-token
    group first. Each group keeps its member events so a row expands to its detail.

    Args:
        events: The timeline events to group.

    Returns:
        One `EventGroup` per (kind, category), members included, sorted by total tokens descending.
    """
    buckets: dict[tuple[EventKind, str], list[ContextEvent]] = {}
    for event in events:
        buckets.setdefault((event.kind, _category(event)), []).append(event)
    groups = [
        EventGroup(
            kind=kind,
            label=label,
            count=len(members),
            tokens=sum(member.tokens for member in members),
            events=members,
        )
        for (kind, label), members in buckets.items()
    ]
    groups.sort(key=lambda group: group.tokens, reverse=True)
    return groups


def summarize_kinds(events: list[ContextEvent]) -> list[KindSummary]:
    """Roll events up per kind (the overview/mini-bar bands), highest-token kind first.

    Args:
        events: The timeline events to roll up.

    Returns:
        One `KindSummary` per kind, sorted by total tokens descending.
    """
    counts: dict[EventKind, list[int]] = {}
    for event in events:
        bucket = counts.setdefault(event.kind, [0, 0])
        bucket[0] += 1
        bucket[1] += event.tokens
    summaries = [
        KindSummary(kind=kind, count=count, tokens=tokens)
        for kind, (count, tokens) in counts.items()
    ]
    summaries.sort(key=lambda summary: summary.tokens, reverse=True)
    return summaries


# Per-session kind roll-ups are deterministic in the transcript bytes, so a project re-open reuses
# them instead of re-reading every transcript. A bounded LRU keyed by file identity (path, mtime,
# size) — a derived-data memo, not domain state; each edit makes a fresh key, so the cap bounds
# memory over a long-lived process.
_KINDS_CACHE: OrderedDict[tuple[str, int, int], list[KindSummary]] = OrderedDict()
_KINDS_CACHE_MAX = 512
# How many of the largest transcripts a project breakdown reads by default — the cap that keeps a
# project of many huge sessions responsive. Callers pass a larger limit (or None) for the full set.
DEFAULT_PROJECT_LIMIT = 50


class _LedgerAccumulator:
    """A ledger bucket under construction — mutable counters, folded into a `LedgerBucket`."""

    def __init__(self, start: date, end: date) -> None:
        self.start = start
        self.end = end
        self.projects: set[str] = set()
        self.session_count = 0
        self.size_bytes = 0
        self.counts: dict[EventKind, list[int]] = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        self.cost_usd = 0.0


def _timestamp_date(value: object) -> date | None:
    """The calendar day of a stored record timestamp, in UTC."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    stamp = parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    return stamp.date()


def _session_kinds(path: Path) -> list[KindSummary]:
    """The per-kind roll-up of one transcript, memoized (bounded LRU) by file identity."""
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    cached = _KINDS_CACHE.get(key)
    if cached is not None:
        _KINDS_CACHE.move_to_end(key)
        return cached
    kinds = summarize_kinds(from_transcript(path).events)
    _KINDS_CACHE[key] = kinds
    if len(_KINDS_CACHE) > _KINDS_CACHE_MAX:
        _KINDS_CACHE.popitem(last=False)
    return kinds


def _summaries_from_counts(counts: dict[EventKind, list[int]]) -> list[KindSummary]:
    """Convert mutable kind counters to sorted API summaries."""
    summaries = [
        KindSummary(kind=kind, count=count, tokens=tokens)
        for kind, (count, tokens) in counts.items()
    ]
    summaries.sort(key=lambda summary: summary.tokens, reverse=True)
    return summaries


def _week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def _bucket_of(day: date, period: LedgerPeriod) -> tuple[str, date, date]:
    if period is LedgerPeriod.daily:
        return day.isoformat(), day, day
    start, end = _week_bounds(day)
    iso_year, iso_week, _ = day.isocalendar()
    return f"{iso_year}-W{iso_week:02d}", start, end


def build_ledger(db_path: Path, period: LedgerPeriod) -> LedgerView:
    """Roll the store into daily or weekly buckets: estimated context by kind, and billed usage.

    Reads the rollups the ingest already maintains rather than replaying transcripts, so this
    costs a few aggregate queries whatever the size of the corpus — and answers for sessions
    whose transcripts have since been deleted, which a filesystem walk cannot.
    """
    if not db_path.exists():
        return LedgerView(period=period, buckets=[])
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        transcripts = conn.execute(
            "SELECT r.source AS source,"
            "       MAX(r.timestamp) AS last_seen,"
            "       COALESCE(MAX(s.size_bytes), 0) AS size_bytes"
            " FROM records r LEFT JOIN ingest_state s ON s.source = r.source"
            " WHERE r.timestamp IS NOT NULL"
            " GROUP BY r.source"
        ).fetchall()
        kind_rows = conn.execute("SELECT source, kind, count, tokens FROM session_kinds").fetchall()
        # Billed usage carries its own day, and a request belongs to a session rather than to any
        # one of the files that session was split across — so it buckets by date, not by transcript.
        billed_rows = conn.execute(
            "SELECT day,"
            "       SUM(input_tokens) AS input_tokens,"
            "       SUM(output_tokens) AS output_tokens,"
            "       SUM(cache_read_input_tokens) AS cache_read_tokens,"
            "       SUM(cache_creation_5m_input_tokens + cache_creation_1h_input_tokens"
            "           + cache_creation_unknown_tokens) AS cache_creation_tokens,"
            "       SUM(cost_usd) AS cost_usd"
            " FROM usage_events WHERE day IS NOT NULL GROUP BY day"
        ).fetchall()
    except sqlite3.DatabaseError:
        logger.warning("could not read %s; serving an empty ledger", db_path)
        return LedgerView(period=period, buckets=[])
    finally:
        conn.close()

    kinds_by_source: dict[str, list[sqlite3.Row]] = {}
    for row in kind_rows:
        kinds_by_source.setdefault(str(row["source"]), []).append(row)

    buckets: dict[str, _LedgerAccumulator] = {}

    def bucket_for(day: date) -> _LedgerAccumulator:
        label, start, end = _bucket_of(day, period)
        acc = buckets.get(label)
        if acc is None:
            acc = _LedgerAccumulator(start=start, end=end)
            buckets[label] = acc
        return acc

    for transcript in transcripts:
        stamp = _timestamp_date(transcript["last_seen"])
        if stamp is None:
            continue
        source = str(transcript["source"])
        acc = bucket_for(stamp)
        acc.projects.add(source.split("/")[0])
        acc.session_count += 1
        acc.size_bytes += int(transcript["size_bytes"])
        for row in kinds_by_source.get(source, []):
            counter = acc.counts.setdefault(EventKind(row["kind"]), [0, 0])
            counter[0] += int(row["count"])
            counter[1] += int(row["tokens"])

    for billed in billed_rows:
        day = _timestamp_date(billed["day"])
        if day is None:
            continue
        acc = bucket_for(day)
        acc.input_tokens += int(billed["input_tokens"] or 0)
        acc.output_tokens += int(billed["output_tokens"] or 0)
        acc.cache_read_tokens += int(billed["cache_read_tokens"] or 0)
        acc.cache_creation_tokens += int(billed["cache_creation_tokens"] or 0)
        acc.cost_usd += float(billed["cost_usd"] or 0.0)

    ledger_buckets = [
        LedgerBucket(
            label=label,
            starts_on=acc.start.isoformat(),
            ends_on=acc.end.isoformat(),
            session_count=acc.session_count,
            project_count=len(acc.projects),
            size_bytes=acc.size_bytes,
            aggregate=_summaries_from_counts(acc.counts),
            input_tokens=acc.input_tokens,
            output_tokens=acc.output_tokens,
            cache_read_tokens=acc.cache_read_tokens,
            cache_creation_tokens=acc.cache_creation_tokens,
            cost_usd=acc.cost_usd,
        )
        for label, acc in buckets.items()
    ]
    ledger_buckets.sort(key=lambda bucket: bucket.starts_on, reverse=True)
    return LedgerView(period=period, buckets=ledger_buckets)


def from_project(
    project_dir: Path,
    window_tokens: int | None = None,
    limit: int | None = DEFAULT_PROJECT_LIMIT,
) -> ProjectBreakdown:
    """Break a whole project (one directory of session transcripts) fully down.

    The `limit` largest transcripts are replayed and rolled up per kind into a `SessionSummary`
    (the drill-down list); the same rollups accumulate into a project-wide per-kind `aggregate`
    (the overview). Per-session rollups are cached by file identity, so a re-open — or raising the
    limit to the full set — is cheap. The full event chain of any one session is fetched on demand
    via `from_transcript`, not carried here.

    Args:
        project_dir: A `~/.claude/projects/<project>` directory holding `<id>.jsonl` transcripts.
        window_tokens: Context window to render against; the model default when omitted.
        limit: Most transcripts to read, largest first; None reads every session.

    Returns:
        The breakdown, sessions ordered largest-transcript first; empty when the dir is absent.
    """
    summaries: list[SessionSummary] = []
    aggregate: dict[EventKind, list[int]] = {}
    if project_dir.is_dir():
        paths = [
            p
            for p in sorted(
                project_dir.glob("*.jsonl"), key=lambda p: p.stat().st_size, reverse=True
            )
            if p.is_file() and SAFE_SESSION_ID.fullmatch(p.stem)
        ]
        for path in paths if limit is None else paths[:limit]:
            kinds = _session_kinds(path)
            stat = path.stat()
            summaries.append(
                SessionSummary(
                    ref=SessionRef(
                        session_id=path.stem,
                        project=project_dir.name,
                        size_bytes=stat.st_size,
                        last_modified=_iso_mtime(stat.st_mtime),
                    ),
                    kinds=kinds,
                    **({"window_tokens": window_tokens} if window_tokens else {}),
                )
            )
            for kind in kinds:
                bucket = aggregate.setdefault(kind.kind, [0, 0])
                bucket[0] += kind.count
                bucket[1] += kind.tokens
    overview = [
        KindSummary(kind=kind, count=count, tokens=tokens)
        for kind, (count, tokens) in aggregate.items()
    ]
    overview.sort(key=lambda summary: summary.tokens, reverse=True)
    return ProjectBreakdown(
        project=project_dir.name,
        aggregate=overview,
        sessions=summaries,
        **({"window_tokens": window_tokens} if window_tokens else {}),
    )


def discover_projects(projects_root: Path) -> list[ProjectRef]:
    """List the projects (transcript directories) under a projects root, largest first.

    Args:
        projects_root: The `~/.claude/projects` directory holding `<project>/<id>.jsonl` files.

    Returns:
        One ref per project that holds at least one transcript, most bytes first; `[]` if the root
        is absent.
    """
    if not projects_root.is_dir():
        return []
    refs: list[ProjectRef] = []
    for entry in projects_root.iterdir():
        if not entry.is_dir():
            continue
        sizes = [p.stat().st_size for p in entry.glob("*.jsonl") if p.is_file()]
        if sizes:
            refs.append(
                ProjectRef(project=entry.name, session_count=len(sizes), total_bytes=sum(sizes))
            )
    refs.sort(key=lambda ref: ref.total_bytes, reverse=True)
    return refs


def resolve_project(projects_root: Path, project: str) -> Path | None:
    """Resolve a project name to its directory, confined to `projects_root`.

    A name that isn't a clean token, or that resolves outside the root, returns None — so a hostile
    name can neither traverse the filesystem nor widen the glob.

    Args:
        projects_root: The projects directory to search.
        project: The bare project directory name to resolve.

    Returns:
        The project directory, or None when no safe match exists.
    """
    if project in (".", "..") or not SAFE_SESSION_ID.fullmatch(project):
        return None
    candidate = projects_root / project
    root = projects_root.resolve()
    if candidate.is_dir() and candidate.resolve().is_relative_to(root):
        return candidate
    return None
