"""Token → USD cost estimation with prompt-caching breakdown.

Numbers below are list pricing as of Anthropic's published rate cards.
**Update the constants when Anthropic publishes new pricing** — these
figures are used for budget evaluation, not actual billing. Verified
costs from the SDK's usage block override these estimates per call.

Cache pricing reflects the standard 5-minute ephemeral cache. Cache
*writes* cost slightly more than baseline input; cache *reads* cost
~10% of baseline input.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    model_id: str
    input_per_mtok: float       # USD per 1M input tokens
    output_per_mtok: float
    cache_read_per_mtok: float
    cache_write_per_mtok: float


# Pricing constants — verify against Anthropic's pricing page before relying.
HAIKU_4_5 = ModelPricing(
    model_id="claude-haiku-4-5-20251001",
    input_per_mtok=0.80,
    output_per_mtok=4.00,
    cache_read_per_mtok=0.08,
    cache_write_per_mtok=1.00,
)

SONNET_4_6 = ModelPricing(
    model_id="claude-sonnet-4-6",
    input_per_mtok=3.00,
    output_per_mtok=15.00,
    cache_read_per_mtok=0.30,
    cache_write_per_mtok=3.75,
)

OPUS_4_7 = ModelPricing(
    model_id="claude-opus-4-7",
    input_per_mtok=15.00,
    output_per_mtok=75.00,
    cache_read_per_mtok=1.50,
    cache_write_per_mtok=18.75,
)

PRICING_BY_MODEL: dict[str, ModelPricing] = {
    HAIKU_4_5.model_id: HAIKU_4_5,
    SONNET_4_6.model_id: SONNET_4_6,
    OPUS_4_7.model_id: OPUS_4_7,
    "haiku": HAIKU_4_5,
    "sonnet": SONNET_4_6,
    "opus": OPUS_4_7,
}


def get_pricing(model: str) -> ModelPricing:
    """Look up pricing for a model alias or exact id; default to Sonnet."""
    return PRICING_BY_MODEL.get(model) or SONNET_4_6


def estimate_cost(
    *,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Return USD estimate for a single call's token usage.

    ``input_tokens`` is uncached prompt tokens (what was actually
    submitted to the model). ``cache_read_tokens`` is what was served
    from the prompt cache. ``cache_write_tokens`` is what was written
    into the cache by this call (only the first call in the TTL window
    pays this).
    """
    p = get_pricing(model)
    return (
        (input_tokens       / 1_000_000) * p.input_per_mtok
        + (output_tokens    / 1_000_000) * p.output_per_mtok
        + (cache_read_tokens  / 1_000_000) * p.cache_read_per_mtok
        + (cache_write_tokens / 1_000_000) * p.cache_write_per_mtok
    )


def project_dept_scan_cost(
    *,
    model: str,
    system_prompt_tokens: int,
    user_prompt_tokens: int,
    output_tokens: int,
    targets: int,
    cache_hits_per_target: bool = True,
) -> dict:
    """Project cost of scanning N targets through one department.

    Assumes one ``cache_write`` for the system prompt (first call) and
    cache reads for every subsequent target within the TTL window.
    Returns a breakdown dict suitable for the cost guide doc.
    """
    p = get_pricing(model)
    # First call: writes cache, charges full input for the user prompt
    first_call = estimate_cost(
        model=model,
        input_tokens=user_prompt_tokens,
        output_tokens=output_tokens,
        cache_write_tokens=system_prompt_tokens,
    )
    # Subsequent calls: cache reads for system prompt, full input for user prompt
    if cache_hits_per_target and targets > 1:
        per_subsequent = estimate_cost(
            model=model,
            input_tokens=user_prompt_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=system_prompt_tokens,
        )
    else:
        # No cache — every call pays full input on the system prompt too
        per_subsequent = estimate_cost(
            model=model,
            input_tokens=system_prompt_tokens + user_prompt_tokens,
            output_tokens=output_tokens,
        )
    total = first_call + per_subsequent * max(0, targets - 1)
    return {
        "model": model,
        "model_pricing": {
            "input_per_mtok": p.input_per_mtok,
            "output_per_mtok": p.output_per_mtok,
            "cache_read_per_mtok": p.cache_read_per_mtok,
            "cache_write_per_mtok": p.cache_write_per_mtok,
        },
        "targets": targets,
        "first_call_usd": round(first_call, 4),
        "per_subsequent_usd": round(per_subsequent, 4),
        "total_usd": round(total, 4),
    }
