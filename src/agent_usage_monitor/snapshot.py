from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from .analytics import by_agent, by_model, by_period, by_period_and_model, summarize
from .models import Agent, SourceStatus, UsageEvent

SCHEMA_VERSION = 2


def build_snapshot(
    events: list[UsageEvent],
    statuses: Iterable[SourceStatus],
    *,
    granularity: str = "day",
    requested_start: datetime | None = None,
    requested_end: datetime | None = None,
    range_label: str = "7d",
    model_filters: list[str] | None = None,
) -> dict:
    status_list = list(statuses)
    totals = summarize(events)
    warnings: list[str] = []
    if any(event.accuracy.value == "estimated" for event in events):
        warnings.append("Estimated events are derived from message text, not provider counters.")
    if not events:
        warnings.append("No usage events found for the selected filters.")
    for status in status_list:
        if status.errors:
            warnings.append(
                f"{status.agent.value} source reported {len(status.errors)} read error(s)."
            )

    agent_summaries = by_agent(events)
    agents: dict[str, dict] = {}
    for agent in Agent:
        summary = agent_summaries.get(agent)
        agents[agent.value] = summary.to_dict() if summary else _empty_summary()
        agents[agent.value]["status"] = "data" if summary else "not_detected"

    models = []
    total_tokens = max(1, totals.usage.total)
    for (agent, model), summary in by_model(events).items():
        models.append(
            {
                "agent": agent.value,
                "model": model,
                **summary.to_dict(),
                "share": round(summary.usage.total / total_tokens * 100, 2),
            }
        )
    models.sort(key=lambda row: row["usage"]["total"], reverse=True)

    timeline = []
    model_buckets = by_period_and_model(events, granularity)
    for period, summary in by_period(events, granularity).items():
        bucket_models = [
            {
                "agent": agent.value,
                "model": model,
                **model_summary.to_dict(),
            }
            for (agent, model), model_summary in model_buckets.get(period, {}).items()
        ]
        bucket_models.sort(key=lambda row: row["usage"]["total"], reverse=True)
        timeline.append({"period": period, **summary.to_dict(), "model_breakdown": bucket_models})

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provenance": {
            "kind": "local_logs",
            "confidence": "mixed" if totals.estimated_events else "exact" if events else "unknown",
        },
        "selection": {
            "range": range_label,
            "start": requested_start.isoformat() if requested_start else None,
            "end": requested_end.isoformat() if requested_end else None,
            "granularity": granularity,
            "models": model_filters or [],
        },
        "totals": totals.to_dict(),
        "agents": agents,
        "models": models,
        "timeline": timeline,
        "observed_range": {
            "start": events[0].timestamp.isoformat() if events else None,
            "end": events[-1].timestamp.isoformat() if events else None,
        },
        "sources": [status.to_dict() for status in status_list],
        "warnings": warnings,
    }


def _empty_summary() -> dict:
    return {
        "usage": {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
            "reasoning": 0,
            "total": 0,
        },
        "cost_usd": 0.0,
        "events": 0,
        "exact_events": 0,
        "estimated_events": 0,
        "models": [],
        "projects": [],
    }
