"""Self-contained HTML flow-graph (Sankey) reports over Claude Code sessions."""

from __future__ import annotations

from .htmlshell import StatTile, render_page
from .ledger import build_page as build_ledger_page
from .sankey import (
    SankeyGraph,
    SankeyLink,
    SankeyNode,
    SessionPage,
    build_page,
    build_page_model,
    token_graph,
    tool_activity_graph,
)

__all__ = [
    "SankeyGraph",
    "SankeyLink",
    "SankeyNode",
    "SessionPage",
    "StatTile",
    "build_ledger_page",
    "build_page",
    "build_page_model",
    "render_page",
    "token_graph",
    "tool_activity_graph",
]
