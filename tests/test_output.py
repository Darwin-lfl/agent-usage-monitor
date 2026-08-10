from datetime import datetime, timedelta, timezone

from rich.console import Console

from agent_usage_monitor.models import Agent, SourceStatus, TokenUsage, UsageEvent
from agent_usage_monitor.output import render_dashboard
from agent_usage_monitor.snapshot import build_snapshot


def _snapshot_and_events(granularity="day"):
    now = datetime.now(timezone.utc)
    events = [
        UsageEvent(
            id="m1",
            agent=Agent.OPENCODE,
            timestamp=now - timedelta(hours=2),
            usage=TokenUsage(input=120_000, output=8_000, cache_read=40_000),
            model="openai/gpt-5",
        ),
        UsageEvent(
            id="m2",
            agent=Agent.OPENCODE,
            timestamp=now - timedelta(minutes=2),
            usage=TokenUsage(input=30_000, output=2_000, cache_read=10_000),
            model="anthropic/claude-sonnet",
        ),
    ]
    status = SourceStatus(
        agent=Agent.OPENCODE,
        paths=["/local/opencode.db"],
        files_scanned=1,
        records_read=2,
        events=2,
    )
    return (
        build_snapshot(events, [status], granularity=granularity, range_label="7d"),
        events,
    )


def test_overview_has_model_and_time_statistics_at_80_columns():
    snapshot, events = _snapshot_and_events()
    console = Console(width=80, record=True, color_system=None)

    console.print(render_dashboard(snapshot, events, "overview", 80))
    output = console.export_text()

    assert "MODEL STATISTICS" in output
    assert "AGENT STATISTICS" in output
    assert "USAGE BY DAY" in output
    assert "openai/gpt-5" in output
    assert "forecast" not in output.lower()
    assert "reset" not in output.lower()


def test_models_view_has_detailed_token_columns():
    snapshot, events = _snapshot_and_events()
    console = Console(width=120, record=True, color_system=None)

    console.print(render_dashboard(snapshot, events, "models", 120))
    output = console.export_text()

    assert "Input" in output
    assert "Output" in output
    assert "Cache" in output
    assert "anthropic/claude-sonnet" in output


def test_timeline_view_reflects_selected_granularity():
    snapshot, events = _snapshot_and_events("hour")
    console = Console(width=80, record=True, color_system=None)

    console.print(render_dashboard(snapshot, events, "timeline", 80))

    assert "USAGE BY HOUR" in console.export_text()


def test_sources_view_includes_path_and_health():
    snapshot, events = _snapshot_and_events()
    console = Console(width=120, record=True, color_system=None)

    console.print(render_dashboard(snapshot, events, "sources", 120))
    output = console.export_text()

    assert "SOURCE HEALTH" in output
    assert "/local/opencode.db" in output
