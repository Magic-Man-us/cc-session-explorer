"""Domain primitives shared across the explorer's lenses (usage, ingest, timeline).

Package-local, not `cc_session_core`'s: these carry a validation constraint
(``ge=0``/``min_length=1``) core's own aliases of the same name don't declare, so a
consolidated re-export here — rather than each lens redeclaring its own copy — is the single
place that constraint lives.
"""

from __future__ import annotations

from typing import Annotated

from cc_session_core import types as core_types
from pydantic import Field

TokenCount = core_types.TokenCount

CostUsd = Annotated[
    float, Field(ge=0, title="Cost (USD)", description="Estimated USD cost at list rates.")
]

RequestCount = Annotated[
    int,
    Field(ge=0, title="Request count", description="A non-negative count of tool-use requests."),
]

ModelKey = Annotated[
    str,
    Field(min_length=1, title="Model key", description="A Claude model id used for pricing."),
]

IdleSeconds = Annotated[
    float,
    Field(
        gt=0,
        title="Idle seconds",
        description="Seconds without a request before a socket-activated server exits.",
    ),
]
