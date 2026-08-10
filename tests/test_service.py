from datetime import datetime, timezone

from agent_usage_monitor.models import Agent, SourceStatus, TokenUsage, UsageEvent
from agent_usage_monitor.service import MeasurementRequest, MeasurementService


class FixtureAdapter:
    def __init__(self, event: UsageEvent) -> None:
        self.event = event
        self.status = SourceStatus(agent=event.agent, paths=["/fixture"])
        self.calls = 0

    def collect(self, _start):
        self.calls += 1
        self.status.files_scanned = 1
        self.status.records_read = 1
        self.status.events = 1
        return [self.event]


def test_measurement_service_builds_snapshot_and_reuses_short_cache(monkeypatch):
    event = UsageEvent(
        id="cached",
        agent=Agent.CODEX,
        timestamp=datetime.now(timezone.utc),
        usage=TokenUsage(input=120, output=30),
        model="openai/gpt-5",
    )
    adapter = FixtureAdapter(event)
    monkeypatch.setattr(
        "agent_usage_monitor.service.build_adapters",
        lambda *_args, **_kwargs: [adapter],
    )
    service = MeasurementService()
    request = MeasurementRequest(agents=[Agent.CODEX])

    _, first = service.measure(request, max_age=2)
    _, second = service.measure(request, max_age=2)

    assert first["totals"]["usage"]["total"] == 150
    assert second is first
    assert adapter.calls == 1


def test_measurement_service_force_refresh_bypasses_cache(monkeypatch):
    event = UsageEvent(
        id="refresh",
        agent=Agent.OPENCODE,
        timestamp=datetime.now(timezone.utc),
        usage=TokenUsage(input=10),
    )
    adapter = FixtureAdapter(event)
    monkeypatch.setattr(
        "agent_usage_monitor.service.build_adapters",
        lambda *_args, **_kwargs: [adapter],
    )
    service = MeasurementService()
    request = MeasurementRequest(agents=[Agent.OPENCODE])

    service.measure(request, max_age=2)
    service.measure(request, max_age=0)

    assert adapter.calls == 2
