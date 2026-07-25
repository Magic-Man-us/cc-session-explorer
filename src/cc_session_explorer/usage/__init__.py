"""The cost/usage dashboard lens over Claude Code and Codex projects.

The sibling lens to the context-token timeline (`/timeline/*`): same transcripts, priced and
rolled up. Serves the SPA's `/api/*` contract — snapshot, tail, buckets, live sessions, and
per-session transcripts — computed from the provider-aware SQLite archive and normalized
``cc_session_core.Session`` views, including active and archived rollouts.
"""

from __future__ import annotations

from cc_session_explorer.usage.router import router

__all__ = ["router"]
