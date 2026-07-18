"""Notional API-list cost estimates for the dashboard and ledger.

All rate arithmetic, including the US-region inference surcharge, is owned by
``cc_session_core.request_cost`` — this module only maps the ledger's raw token counts
onto a ``Usage`` so both the live scan and historical rows price identically.
"""

from __future__ import annotations

from cc_session_core import CacheCreation, Usage, request_cost

from cc_session_explorer.base import FrozenModel
from cc_session_explorer.types import CostUsd, ModelKey, TokenCount


def _counts_usage(
    input_tokens: TokenCount,
    output_tokens: TokenCount,
    cache_read_tokens: TokenCount,
    cache_creation_5m_tokens: TokenCount,
    cache_creation_1h_tokens: TokenCount,
    inference_geo: str | None = None,
) -> Usage:
    """A ``Usage`` carrying raw ledger counts, so core owns all rate arithmetic."""
    return Usage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read_tokens,
        cache_creation_input_tokens=cache_creation_5m_tokens + cache_creation_1h_tokens,
        cache_creation=CacheCreation(
            ephemeral_5m_input_tokens=cache_creation_5m_tokens,
            ephemeral_1h_input_tokens=cache_creation_1h_tokens,
        ),
        inference_geo=inference_geo,
    )


def estimate_cost(
    model: ModelKey | None,
    input_tokens: TokenCount,
    output_tokens: TokenCount,
    cache_read_tokens: TokenCount,
    cache_creation_tokens: TokenCount,
) -> CostUsd:
    """Cost of a turn, pricing all cache-creation tokens at the 5-minute write rate."""
    usage = _counts_usage(input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, 0)
    cost = request_cost(model, usage)
    return round(cost, 4) if cost is not None else 0.0


class DetailedCostInputs(FrozenModel):
    """One ledger row's raw token counts, priced with the 5m/1h/unknown cache split."""

    model: ModelKey | None
    input_tokens: TokenCount
    output_tokens: TokenCount
    cache_read_tokens: TokenCount
    cache_creation_5m_tokens: TokenCount
    cache_creation_1h_tokens: TokenCount
    cache_creation_unknown_tokens: TokenCount
    inference_geo: str | None


def estimate_detailed_cost(inputs: DetailedCostInputs) -> CostUsd:
    """Cost of a ledger row, honouring the 5m/1h/unknown cache split; core applies the
    US-inference surcharge from ``inference_geo``. Unknown-tier cache-creation tokens are
    priced at the 5-minute write rate."""
    usage = _counts_usage(
        inputs.input_tokens,
        inputs.output_tokens,
        inputs.cache_read_tokens,
        inputs.cache_creation_5m_tokens + inputs.cache_creation_unknown_tokens,
        inputs.cache_creation_1h_tokens,
        inputs.inference_geo,
    )
    cost = request_cost(inputs.model, usage)
    return round(cost, 4) if cost is not None else 0.0
