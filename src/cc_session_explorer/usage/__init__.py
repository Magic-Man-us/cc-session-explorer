"""The cost/usage dashboard lens: token spend and estimated USD over all Claude Code projects.

The sibling lens to the context-token timeline (`/timeline/*`): same transcripts, priced and
rolled up. Serves the SPA's `/api/*` contract — snapshot, tail, buckets, live sessions, and
per-session transcripts — computed straight off `~/.claude/projects` via cc-session-core with
an mtime-keyed per-file cache, merged with `cc_session_explorer.history`'s ledger for sessions
whose transcripts have rotated off disk.
"""

from __future__ import annotations

from cc_session_explorer.usage.router import router

__all__ = ["router"]
