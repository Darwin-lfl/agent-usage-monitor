from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import Accuracy, Agent, TokenUsage, UsageEvent

GRANULARITIES = ("hour", "day", "week", "month")


@dataclass(slots=True)
class UsageSummary:
    usage: TokenUsage = field(default_factory=TokenUsage)
    cost_usd: float = 0.0
    events: int = 0
    exact_events: int = 0
    estimated_events: int = 0
    models: set[str] = field(default_factory=set)
    projects: set[str] = field(default_factory=set)

    def add(self, event: UsageEvent) -> None:
        self.usage = self.usage + event.usage
        self.cost_usd += event.cost_usd or 0
        self.events += 1
        self.exact_events += event.accuracy is Accuracy.EXACT
        self.estimated_events += event.accuracy is Accuracy.ESTIMATED
        self.models.add(event.model)
        self.projects.add(event.project)

    def to_dict(self) -> dict:
        return {
            "usage": self.usage.to_dict(),
            "cost_usd": round(self.cost_usd, 6),
            "events": self.events,
            "exact_events": self.exact_events,
            "estimated_events": self.estimated_events,
            "models": sorted(self.models),
            "projects": sorted(self.projects),
        }


def summarize(events: Iterable[UsageEvent]) -> UsageSummary:
    result = UsageSummary()
    for event in events:
        result.add(event)
    return result


def by_agent(events: Iterable[UsageEvent]) -> dict[Agent, UsageSummary]:
    result: dict[Agent, UsageSummary] = defaultdict(UsageSummary)
    for event in events:
        result[event.agent].add(event)
    return dict(result)


def by_model(events: Iterable[UsageEvent]) -> dict[tuple[Agent, str], UsageSummary]:
    result: dict[tuple[Agent, str], UsageSummary] = defaultdict(UsageSummary)
    for event in events:
        result[(event.agent, event.model)].add(event)
    return dict(result)


def by_period(events: Iterable[UsageEvent], granularity: str) -> dict[str, UsageSummary]:
    if granularity not in GRANULARITIES:
        raise ValueError(f"unsupported granularity: {granularity}")
    result: dict[str, UsageSummary] = defaultdict(UsageSummary)
    for event in events:
        result[period_key(event, granularity)].add(event)
    return dict(sorted(result.items()))


def by_period_and_model(
    events: Iterable[UsageEvent], granularity: str
) -> dict[str, dict[tuple[Agent, str], UsageSummary]]:
    result: dict[str, dict[tuple[Agent, str], UsageSummary]] = defaultdict(
        lambda: defaultdict(UsageSummary)
    )
    for event in events:
        result[period_key(event, granularity)][(event.agent, event.model)].add(event)
    return {period: dict(models) for period, models in sorted(result.items())}


def period_key(event: UsageEvent, granularity: str) -> str:
    local = event.timestamp.astimezone()
    if granularity == "hour":
        return local.strftime("%Y-%m-%d %H:00")
    if granularity == "day":
        return local.strftime("%Y-%m-%d")
    if granularity == "week":
        iso_year, iso_week, _ = local.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "month":
        return local.strftime("%Y-%m")
    raise ValueError(f"unsupported granularity: {granularity}")
