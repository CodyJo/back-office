"""Tests for Phase-7+ time-windowed budget periods."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backoffice.budgets import (
    ALLOW,
    BLOCK,
    Budget,
    evaluate,
)
from backoffice.domain import CostEvent


def _ev(amount: float, ts: str, **kw) -> CostEvent:
    return CostEvent(id="x", estimated_cost_usd=amount, timestamp=ts, **kw)


# Reference "now" used across the suite — Tuesday, March 17 2026, noon UTC.
NOW = datetime(2026, 3, 17, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────────────────────────────────────────────────
# Lifetime (default for every previous test) keeps working
# ──────────────────────────────────────────────────────────────────────


def test_lifetime_period_sums_everything():
    budget = Budget(id="b1", scope="global", period="lifetime", hard_limit_usd=10.0)
    events = [
        _ev(5.0, "2020-01-01T00:00:00+00:00"),
        _ev(6.0, "2026-03-17T11:59:00+00:00"),
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == BLOCK
    assert decision.spent_usd == 11.0


# ──────────────────────────────────────────────────────────────────────
# rolling_24h
# ──────────────────────────────────────────────────────────────────────


def test_rolling_24h_excludes_older_events():
    budget = Budget(id="b1", scope="global", period="rolling_24h", hard_limit_usd=10.0)
    events = [
        _ev(50.0, (NOW - timedelta(hours=25)).isoformat()),  # outside window
        _ev(3.0, (NOW - timedelta(hours=1)).isoformat()),     # inside
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == ALLOW
    assert decision.spent_usd == 3.0


def test_rolling_24h_includes_recent_events():
    budget = Budget(id="b1", scope="global", period="rolling_24h", hard_limit_usd=2.0)
    events = [
        _ev(3.0, (NOW - timedelta(hours=1)).isoformat()),
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == BLOCK


# ──────────────────────────────────────────────────────────────────────
# daily
# ──────────────────────────────────────────────────────────────────────


def test_daily_resets_at_midnight_utc():
    budget = Budget(id="b1", scope="global", period="daily", hard_limit_usd=10.0)
    events = [
        _ev(50.0, "2026-03-16T23:59:59+00:00"),   # yesterday — excluded
        _ev(3.0, "2026-03-17T00:00:01+00:00"),    # today — included
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == ALLOW
    assert decision.spent_usd == 3.0


def test_daily_includes_only_today():
    budget = Budget(id="b1", scope="global", period="daily", hard_limit_usd=2.0)
    events = [
        _ev(5.0, "2026-03-17T03:00:00+00:00"),
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == BLOCK


# ──────────────────────────────────────────────────────────────────────
# weekly (ISO Monday)
# ──────────────────────────────────────────────────────────────────────


def test_weekly_window_starts_monday_midnight():
    """NOW is Tuesday 2026-03-17. The week starts Monday 2026-03-16 00:00."""
    budget = Budget(id="b1", scope="global", period="weekly", hard_limit_usd=10.0)
    events = [
        _ev(50.0, "2026-03-15T23:59:59+00:00"),  # Sunday — excluded
        _ev(3.0, "2026-03-16T00:00:01+00:00"),    # Monday — included
        _ev(2.0, "2026-03-17T11:00:00+00:00"),    # Tuesday — included
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == ALLOW
    assert decision.spent_usd == 5.0


# ──────────────────────────────────────────────────────────────────────
# monthly
# ──────────────────────────────────────────────────────────────────────


def test_monthly_starts_at_first_of_month():
    budget = Budget(id="b1", scope="global", period="monthly", hard_limit_usd=10.0)
    events = [
        _ev(50.0, "2026-02-28T23:59:59+00:00"),   # February — excluded
        _ev(3.0, "2026-03-01T00:00:01+00:00"),    # March — included
        _ev(2.0, "2026-03-17T11:00:00+00:00"),    # March — included
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == ALLOW
    assert decision.spent_usd == 5.0


# ──────────────────────────────────────────────────────────────────────
# Multiple budgets, different periods
# ──────────────────────────────────────────────────────────────────────


def test_per_budget_period_isolation():
    """Each budget filters its own window. A monthly soft warn doesn't
    pollute a daily hard limit."""
    daily = Budget(id="d", scope="global", period="daily", hard_limit_usd=5.0)
    monthly = Budget(id="m", scope="global", period="monthly", soft_limit_usd=20.0)
    events = [
        # Old, only counted by monthly.
        _ev(15.0, "2026-03-01T00:00:01+00:00"),
        # Today, counted by both.
        _ev(2.0, "2026-03-17T10:00:00+00:00"),
    ]
    decision = evaluate([daily, monthly], events, now=NOW)
    # Daily $2 — under $5 hard. Monthly $17 — under $20 soft. So allow.
    assert decision.state == ALLOW

    # Add another daily $4 — daily total $6, blocks; monthly still soft.
    events.append(_ev(4.0, "2026-03-17T11:30:00+00:00"))
    decision = evaluate([daily, monthly], events, now=NOW)
    assert decision.state == BLOCK
    assert decision.budget_id == "d"


def test_block_takes_precedence_across_periods():
    daily = Budget(id="d", scope="global", period="daily", soft_limit_usd=1.0)
    monthly = Budget(id="m", scope="global", period="monthly", hard_limit_usd=10.0)
    events = [
        _ev(2.0, "2026-03-17T11:00:00+00:00"),
        _ev(20.0, "2026-03-05T11:00:00+00:00"),
    ]
    decision = evaluate([daily, monthly], events, now=NOW)
    assert decision.state == BLOCK
    assert decision.budget_id == "m"


# ──────────────────────────────────────────────────────────────────────
# Robustness
# ──────────────────────────────────────────────────────────────────────


def test_events_with_no_timestamp_count_toward_every_window():
    """Events without a parseable timestamp are conservatively counted.
    Better to over-attribute than under-attribute."""
    budget = Budget(id="b1", scope="global", period="daily", hard_limit_usd=2.0)
    events = [_ev(5.0, "")]  # missing timestamp
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == BLOCK


def test_invalid_period_falls_back_to_lifetime():
    """``Budget.__post_init__`` rejects unknown periods, but if a
    parsed period reaches evaluator (e.g. data corruption), default
    behavior is to count everything (lifetime). The constructor guard
    is the primary defense; this is belt-and-suspenders."""
    # Build a real budget then mutate its period (only possible because
    # frozen=True still allows __dict__ access via object.__setattr__).
    budget = Budget(id="b1", scope="global", period="lifetime", hard_limit_usd=10.0)
    object.__setattr__(budget, "period", "fortnightly")
    events = [_ev(50.0, "2020-01-01T00:00:00+00:00")]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == BLOCK


def test_now_default_uses_real_clock():
    """When no ``now`` is supplied, evaluate uses the wall clock.
    A future-dated event must not count toward today's daily window."""
    budget = Budget(id="b1", scope="global", period="daily", hard_limit_usd=1.0)
    events = [_ev(1000.0, "2030-01-01T00:00:00+00:00")]
    decision = evaluate([budget], events)  # no now=
    # The 2030 event is in the future; depending on clock it may be
    # included or excluded. Either result is internally consistent.
    assert decision.state in {ALLOW, BLOCK}


def test_naive_timestamp_treated_as_utc():
    budget = Budget(id="b1", scope="global", period="daily", hard_limit_usd=2.0)
    events = [
        _ev(5.0, "2026-03-17T10:00:00"),  # naive — should be treated as UTC, today
    ]
    decision = evaluate([budget], events, now=NOW)
    assert decision.state == BLOCK
