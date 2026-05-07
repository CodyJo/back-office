"""Anthropic SDK client with prompt caching + cost recording.

Calls into the ``anthropic`` Python SDK directly. Designed as the
ancestor of a future replacement for the ``claude`` CLI shell-out —
for now it's available for any caller that wants caching benefits
(Haiku triage, batch evaluations, future scanner refinement).

Falls back cleanly when the SDK isn't installed or no API key is set:
returns a :class:`LLMResult` with ``error="no-api-key"`` /
``error="anthropic-sdk-not-installed"`` so callers can branch
without try/except gymnastics.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from backoffice.llm.cost_estimator import estimate_cost, get_pricing

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Model tier aliases
# ──────────────────────────────────────────────────────────────────────

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-4-6"
OPUS = "claude-opus-4-7"

# Friendly aliases callers can use without pinning version IDs
TIER_TO_MODEL: dict[str, str] = {
    "haiku": HAIKU,
    "sonnet": SONNET,
    "opus": OPUS,
}


@dataclass
class LLMResult:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    estimated_cost_usd: float = 0.0
    model: str = ""
    error: str = ""


def _resolve_model(model_or_tier: str) -> str:
    """Map 'haiku' / 'sonnet' / 'opus' → exact model id; pass-through otherwise."""
    return TIER_TO_MODEL.get(model_or_tier.lower(), model_or_tier)


def call_anthropic(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str = "haiku",
    max_tokens: int = 4096,
    cache_system: bool = True,
    record_event: bool = True,
    target: str | None = None,
    department: str | None = None,
) -> LLMResult:
    """Single-turn message call with optional system-prompt caching.

    Records a cost event to ``cost-events.jsonl`` when ``record_event``
    is True, so :func:`backoffice.budgets.evaluate` sees the spend.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return LLMResult(text="", model=_resolve_model(model), error="no-api-key")

    try:
        import anthropic  # noqa: PLC0415 — optional dep
    except ImportError:
        return LLMResult(text="", model=_resolve_model(model),
                         error="anthropic-sdk-not-installed")

    resolved_model = _resolve_model(model)

    system_block: list[dict] = [
        {"type": "text", "text": system_prompt}
    ]
    if cache_system and len(system_prompt) >= 1024:
        # Anthropic's minimum cacheable size is ~1K tokens; we use chars as a
        # cheap heuristic. False negatives just mean no cache; never an error.
        system_block[0]["cache_control"] = {"type": "ephemeral"}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=resolved_model,
            max_tokens=max_tokens,
            system=system_block,
            messages=[{"role": "user", "content": user_prompt}],
        )
    except Exception as exc:
        logger.warning("Anthropic API call failed: %s", exc)
        return LLMResult(text="", model=resolved_model, error=f"api-error:{type(exc).__name__}")

    # Extract content + usage. The SDK returns content as a list of blocks.
    text_parts = []
    for block in response.content:
        if getattr(block, "type", "") == "text":
            text_parts.append(getattr(block, "text", ""))
    text = "".join(text_parts)

    usage = getattr(response, "usage", None)
    input_tok = int(getattr(usage, "input_tokens", 0) or 0)
    output_tok = int(getattr(usage, "output_tokens", 0) or 0)
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)

    cost = estimate_cost(
        model=resolved_model,
        input_tokens=input_tok,
        output_tokens=output_tok,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )

    if record_event:
        try:
            from backoffice.budgets import record_cost
            from backoffice.store import FileStore
            record_cost(
                FileStore(),
                provider="anthropic",
                model=resolved_model,
                input_tokens=input_tok + cache_read + cache_write,
                output_tokens=output_tok,
                estimated_cost_usd=cost,
                source="provider_api",
                target=target,
                agent_id=f"backoffice.llm.{department}" if department else "backoffice.llm",
            )
        except Exception:
            logger.exception("failed to record cost event")

    return LLMResult(
        text=text,
        input_tokens=input_tok,
        output_tokens=output_tok,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        estimated_cost_usd=cost,
        model=resolved_model,
    )


def has_api_key() -> bool:
    """True iff an ANTHROPIC_API_KEY is in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def has_sdk() -> bool:
    """True iff the anthropic SDK is importable."""
    try:
        import anthropic  # noqa: F401, PLC0415
        return True
    except ImportError:
        return False


def get_model_for_tier(tier: str) -> str:
    """Return the canonical model id for a tier alias."""
    return _resolve_model(tier)


def cost_floor(model: str) -> float:
    """Cheapest-possible per-call USD floor (1 input token, 1 output token).

    Used by callers that want a sanity check before hitting the API.
    """
    p = get_pricing(model)
    return (1 / 1_000_000) * (p.input_per_mtok + p.output_per_mtok)
