from datetime import datetime, timedelta, timezone

import pytest

from agent_usage_monitor.cli import (
    _matches_model,
    _parse_agent_paths,
    _refresh_time_selection,
    _resolve_time_range,
    parser,
)
from agent_usage_monitor.models import Agent


def test_periodic_refresh_is_disabled_by_default():
    assert parser().parse_args([]).refresh_rate == 0


def test_web_subcommand_dispatches_without_starting_tui(monkeypatch):
    calls = []
    monkeypatch.setattr("agent_usage_monitor.web.run_web", lambda **kwargs: calls.append(kwargs))

    from agent_usage_monitor.cli import main

    main(["web", "--port", "9100", "--no-open", "--exact-only"])

    assert calls == [
        {
            "port": 9100,
            "open_browser": False,
            "custom_paths": {},
            "include_estimates": False,
        }
    ]


def test_parse_agent_paths():
    paths = _parse_agent_paths(["claude=/tmp/claude", "claude=/tmp/other"])

    assert len(paths[Agent.CLAUDE]) == 2


@pytest.mark.parametrize("value", ["unknown=/tmp", "missing_equals"])
def test_bad_agent_path(value):
    with pytest.raises(ValueError):
        _parse_agent_paths([value])


def test_resolve_relative_time_range():
    now = datetime(2026, 8, 8, 12, tzinfo=timezone.utc)

    selection = _resolve_time_range("7d", now=now)

    assert selection.start == datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    assert selection.end == now
    assert selection.rolling


def test_relative_range_rolls_forward_during_live_refresh():
    initial = datetime(2026, 8, 8, 12, tzinfo=timezone.utc)
    later = initial + timedelta(hours=2)
    selection = _resolve_time_range("24h", now=initial)

    refreshed = _refresh_time_selection(selection, later)

    assert refreshed.end == later
    assert refreshed.start == later - timedelta(hours=24)


def test_custom_date_range_uses_whole_end_day():
    selection = _resolve_time_range("custom", "2026-08-01", "2026-08-08")

    assert selection.start is not None
    assert selection.start.astimezone().date().isoformat() == "2026-08-01"
    assert selection.end.astimezone().date().isoformat() == "2026-08-08"
    assert selection.end.astimezone().hour == 23
    assert not selection.rolling


def test_invalid_custom_range_is_rejected():
    with pytest.raises(ValueError, match="requires --start"):
        _resolve_time_range("custom")


@pytest.mark.parametrize(
    ("model", "patterns", "expected"),
    [
        ("openai/gpt-5", ["gpt-5"], True),
        ("openai/gpt-5", ["openai/*"], True),
        ("anthropic/claude", ["gpt*", "gemini"], False),
    ],
)
def test_model_filter_supports_substrings_and_globs(model, patterns, expected):
    assert _matches_model(model, patterns) is expected
