"""Anthropic SDK integration with prompt caching + cost recording.

This is an opt-in alternative to the ``claude`` CLI shell-out used by
the existing agents. It exists so the Back Office can:

* Cache large department system prompts via ``cache_control`` (one
  ~10x cost reduction after the first call within the 5-min TTL).
* Pick a model tier per task (haiku 4.5 / sonnet 4.6 / opus 4.7).
* Record cost events to ``results/cost-events.jsonl`` so the
  :mod:`backoffice.budgets` gates have real spend data to evaluate.
* Fall back gracefully when no ``ANTHROPIC_API_KEY`` is set —
  callers see a structured ``no-api-key`` error and route around.

Public entry points::

    from backoffice.llm.client import call_anthropic, ModelTier
    from backoffice.llm.cost_estimator import estimate_cost
"""
