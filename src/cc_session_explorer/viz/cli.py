"""``cc-session-sankey`` — render a Claude Code session to a self-contained Sankey page."""

from __future__ import annotations

import argparse
import webbrowser
from pathlib import Path

from cc_session_core import DEFAULT_PROJECTS_ROOT, Session, resolve_session_file

from .sankey import build_page


def _resolve(target: str | None) -> Path:
    """A .jsonl path as-is, a session id/prefix looked up under ~/.claude/projects,
    or the most-recently-modified session when omitted."""
    if target:
        path = resolve_session_file(target)
        if path is None:
            raise SystemExit(f"no session file found for {target!r}")
        return path
    sessions = sorted(
        DEFAULT_PROJECTS_ROOT.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not sessions:
        raise SystemExit(f"no sessions found under {DEFAULT_PROJECTS_ROOT}")
    return sessions[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a Claude Code session to a self-contained Sankey HTML page."
    )
    parser.add_argument(
        "session",
        nargs="?",
        help="a .jsonl path, a session id/prefix, or omit for the most recent session",
    )
    parser.add_argument(
        "-o", "--out", help="output HTML path (default: ./<session-id>.sankey.html)"
    )
    parser.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = parser.parse_args(argv)

    src = _resolve(args.session)
    out = Path(args.out).expanduser() if args.out else Path.cwd() / f"{src.stem}.sankey.html"
    out.write_text(build_page(Session.load(src)), encoding="utf-8")
    print(f"wrote {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
