"""Viz-domain primitives for the Sankey flow graphs.

cc_session_core owns the transcript primitives; these are the presentation-layer ones
(node ids, tiers, flow values) that only the flow graphs use.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

SankeyNodeId = Annotated[str, Field(title="Sankey node id")]
SankeyLabel = Annotated[str, Field(title="Sankey node label")]
NodeGroup = Annotated[str, Field(title="Node group", description="Key a node/link is colored by.")]
FlowValue = Annotated[
    float, Field(ge=0, title="Flow value", description="Ribbon weight (conserves).")
]
Tier = Annotated[int, Field(ge=0, title="Sankey tier", description="Left-to-right column index.")]
SankeyTitle = Annotated[str, Field(title="Graph title")]
