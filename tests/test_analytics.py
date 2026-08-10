from datetime import datetime, timedelta, timezone

import pytest

from agent_usage_monitor.analytics import by_period, by_period_and_model, summarize
from agent_usage_monitor.models import Accuracy, Agent, TokenUsage, UsageEvent
from agent_usage_monitor.snapshot import build_snapshot


def event(identifier, timestamp, total, model="model-a", agent=Agent.CLAUDE):
    return UsageEvent(
        id=identifier,
        agent=agent,
        timestamp=timestamp,
        usage=TokenUsage(input=total),
        model=model,
        accuracy=Accuracy.EXACT,
    )


def test_summaries_and_hour_granularity():
    now = datetime(2026, 8, 8, 10, 15, tzinfo=timezone.utc)
    events = [event("a", now, 100), event("b", now + timedelta(hours=1), 50)]

    periods = by_period(events, "hour")

    assert summarize(events).usage.total == 150
    assert list(periods) == ["2026-08-08 18:00", "2026-08-08 19:00"]


@pytest.mark.parametrize(
    ("granularity", "expected"),
    [
        ("day", "2026-08-08"),
        ("week", "2026-W32"),
        ("month", "2026-08"),
    ],
)
def test_supported_calendar_granularities(granularity, expected):
    value = datetime(2026, 8, 8, 10, tzinfo=timezone.utc)

    assert list(by_period([event("a", value, 1)], granularity)) == [expected]


def test_period_model_breakdown():
    now = datetime(2026, 8, 8, 10, tzinfo=timezone.utc)
    events = [event("a", now, 100, "model-a"), event("b", now, 50, "model-b")]

    breakdown = next(iter(by_period_and_model(events, "day").values()))

    assert breakdown[(Agent.CLAUDE, "model-a")].usage.total == 100
    assert breakdown[(Agent.CLAUDE, "model-b")].usage.total == 50


def test_snapshot_v2_contains_models_and_timeline_without_prediction_fields():
    now = datetime.now(timezone.utc)
    events = [event("a", now - timedelta(minutes=2), 85, "claude-sonnet")]

    snapshot = build_snapshot(events, [], granularity="hour", range_label="24h")
    serialized = repr(snapshot).lower()

    assert snapshot["schema_version"] == 2
    assert snapshot["models"][0]["model"] == "claude-sonnet"
    assert snapshot["timeline"][0]["period"]
    assert snapshot["selection"]["granularity"] == "hour"
    for removed in ("forecast", "projected", "reset", "tokens_per_minute", "active_sessions"):
        assert removed not in serialized
