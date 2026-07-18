"""Notional API-list pricing adapters over cc_session_core: rates match Anthropic's published list,
including the Fable family and the unknown-cache / geo handling that ``cost_for`` lacks."""

from __future__ import annotations

from cc_session_core import CacheCreation, Usage, request_cost

from cc_session_explorer.history.pricing import (
    DetailedCostInputs,
    estimate_cost,
    estimate_detailed_cost,
)

# Anthropic published list, USD per million tokens (input, output). Cache multipliers are
# universal: read = 0.1x input, write-5m = 1.25x input, write-1h = 2.0x input.
# claude-sonnet-5 is asserted against core directly below — its rate is date-gated
# (introductory through 2026-08-31), so a fixed figure here would go stale.
_LIST = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-1": (15.0, 75.0),  # legacy opus
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5": (10.0, 50.0),
}


def _inputs(
    model: str | None,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_5m_tokens: int = 0,
    cache_creation_1h_tokens: int = 0,
    cache_creation_unknown_tokens: int = 0,
    inference_geo: str | None = None,
) -> DetailedCostInputs:
    return DetailedCostInputs(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_5m_tokens=cache_creation_5m_tokens,
        cache_creation_1h_tokens=cache_creation_1h_tokens,
        cache_creation_unknown_tokens=cache_creation_unknown_tokens,
        inference_geo=inference_geo,
    )


def test_rates_match_published_list() -> None:
    for model, (inp, out) in _LIST.items():
        assert estimate_detailed_cost(_inputs(model, input_tokens=1_000_000)) == round(inp, 4)
        assert estimate_detailed_cost(_inputs(model, output_tokens=1_000_000)) == round(out, 4)
        assert estimate_detailed_cost(_inputs(model, cache_read_tokens=1_000_000)) == round(
            inp * 0.1, 4
        )
        assert estimate_detailed_cost(_inputs(model, cache_creation_5m_tokens=1_000_000)) == round(
            inp * 1.25, 4
        )
        assert estimate_detailed_cost(_inputs(model, cache_creation_1h_tokens=1_000_000)) == round(
            inp * 2.0, 4
        )


def test_sonnet_5_matches_core_request_cost() -> None:
    # Sonnet 5's rate is date-gated in core (intro through 2026-08-31); the ledger
    # estimate must track whatever core resolves, not a frozen figure.
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        cache_creation=CacheCreation(ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=0),
    )
    core_cost = request_cost("claude-sonnet-5", usage)
    assert core_cost is not None
    expected = round(core_cost, 4)
    assert estimate_detailed_cost(_inputs("claude-sonnet-5", input_tokens=1_000_000)) == expected
    assert estimate_cost("claude-sonnet-5", 1_000_000, 0, 0, 0) == expected


def test_fable_is_priced_not_zero() -> None:
    # Regression: "fable"/"mythos" used to fall through the family matcher -> $0.
    assert estimate_detailed_cost(_inputs("claude-fable-5", input_tokens=1_000_000)) == 10.0
    assert estimate_cost("claude-fable-5", 1_000_000, 0, 0, 0) == 10.0
    assert estimate_detailed_cost(_inputs("claude-mythos-5", output_tokens=1_000_000)) == 50.0


def test_unknown_cache_tier_is_priced() -> None:
    # cc_session_core's cost_for ignores unknown-TTL cache tokens; the ledger pricing
    # prices them at the 5-minute write rate (6.25 for opus).
    inputs = _inputs("claude-opus-4-8", cache_creation_unknown_tokens=1_000_000)
    assert estimate_detailed_cost(inputs) == 6.25


def test_inference_geo_us_surcharge() -> None:
    base = estimate_detailed_cost(_inputs("claude-opus-4-8", input_tokens=1_000_000))
    us = estimate_detailed_cost(
        _inputs("claude-opus-4-8", input_tokens=1_000_000, inference_geo="us")
    )
    assert us == round(base * 1.1, 4)


def test_ledger_and_live_scan_price_the_same_us_turn_identically() -> None:
    # R4: the live-scan path (usage/scan.py) prices a turn by calling core's
    # request_cost directly on the parsed Usage; the ledger prices the same raw counts
    # through estimate_detailed_cost. Both must agree, surcharge included, or the
    # dashboard's merged total depends on whether a transcript is still on disk.
    usage = Usage(
        input_tokens=1_000_000,
        output_tokens=0,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        cache_creation=CacheCreation(ephemeral_5m_input_tokens=0, ephemeral_1h_input_tokens=0),
        inference_geo="us",
    )
    live_scan_cost = request_cost("claude-opus-4-8", usage)
    ledger_cost = estimate_detailed_cost(
        _inputs("claude-opus-4-8", input_tokens=1_000_000, inference_geo="us")
    )
    assert live_scan_cost is not None
    assert ledger_cost == round(live_scan_cost, 4)


def test_unknown_model_is_free() -> None:
    assert estimate_detailed_cost(_inputs("<synthetic>", input_tokens=1_000_000)) == 0.0
    assert estimate_detailed_cost(_inputs(None, input_tokens=1_000_000)) == 0.0
