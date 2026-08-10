from __future__ import annotations

import fnmatch
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from datetime import time as datetime_time
from pathlib import Path
from time import monotonic

from .adapters import build_adapters
from .models import Agent, UsageEvent
from .output import write_state
from .snapshot import build_snapshot
from .warehouse import Warehouse

RANGES = ("today", "24h", "7d", "30d", "90d", "all", "custom")


@dataclass(frozen=True, slots=True)
class TimeSelection:
    start: datetime | None
    end: datetime
    label: str
    rolling: bool


@dataclass(slots=True)
class MeasurementRequest:
    agents: list[Agent] = field(default_factory=lambda: list(Agent))
    models: list[str] = field(default_factory=list)
    range_name: str = "7d"
    start: str | None = None
    end: str | None = None
    granularity: str = "day"
    custom_paths: dict[Agent, list[Path]] = field(default_factory=dict)
    include_estimates: bool = True
    warehouse_file: Path | None = None
    state_file: Path | None = None


class MeasurementService:
    """Thread-safe entry point shared by CLI, TUI, and local web clients."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cache: dict[tuple, tuple[float, list[UsageEvent], dict]] = {}

    def measure(
        self, request: MeasurementRequest, *, max_age: float = 0
    ) -> tuple[list[UsageEvent], dict]:
        key = _request_key(request)
        with self._lock:
            cached = self._cache.get(key)
            if max_age > 0 and cached and monotonic() - cached[0] <= max_age:
                return list(cached[1]), cached[2]

            selection = resolve_time_range(
                request.range_name,
                request.start,
                request.end,
            )
            adapters = build_adapters(
                request.agents,
                request.custom_paths,
                include_estimates=request.include_estimates,
            )
            events, snapshot = measure_adapters(
                adapters,
                selection,
                granularity=request.granularity,
                model_filters=request.models,
                selected_agents=request.agents,
                warehouse_file=request.warehouse_file,
                state_file=request.state_file,
            )
            self._cache[key] = (monotonic(), list(events), snapshot)
            if len(self._cache) > 24:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest, None)
            return events, snapshot


def measure_adapters(
    adapters,
    selection: TimeSelection,
    *,
    granularity: str,
    model_filters: list[str],
    selected_agents: list[Agent] | None = None,
    warehouse_file: Path | None = None,
    state_file: Path | None = None,
) -> tuple[list[UsageEvent], dict]:
    selection = refresh_time_selection(selection)
    events: list[UsageEvent] = []
    for adapter in adapters:
        adapter.status.files_scanned = adapter.status.records_read = adapter.status.events = 0
        adapter.status.errors.clear()
        events.extend(adapter.collect(selection.start))
    events = list({event.id: event for event in events}.values())
    if warehouse_file:
        warehouse = Warehouse(warehouse_file)
        warehouse.store(events)
        events = warehouse.load(selection.start)
    selected = set(selected_agents) if selected_agents else None
    events = [
        event
        for event in events
        if event.timestamp <= selection.end
        and (selected is None or event.agent in selected)
        and matches_model(event.model, model_filters)
    ]
    events.sort(key=lambda event: event.timestamp)
    snapshot = build_snapshot(
        events,
        [adapter.status for adapter in adapters],
        granularity=granularity,
        requested_start=selection.start,
        requested_end=selection.end,
        range_label=selection.label,
        model_filters=model_filters,
    )
    if state_file:
        write_state(state_file, snapshot)
    return events, snapshot


def resolve_time_range(
    range_name: str,
    start_value: str | None = None,
    end_value: str | None = None,
    now: datetime | None = None,
) -> TimeSelection:
    now = now or datetime.now(timezone.utc)
    rolling = end_value is None
    end = _parse_boundary(end_value, end=True) if end_value else now
    if start_value:
        start = _parse_boundary(start_value, end=False)
        label = "custom"
    elif range_name == "custom":
        raise ValueError("--range custom requires --start")
    elif range_name == "all":
        start, label = None, "all"
    elif range_name == "today":
        local_now = now.astimezone()
        start = datetime.combine(local_now.date(), datetime_time.min, local_now.tzinfo).astimezone(
            timezone.utc
        )
        label = "today"
    else:
        try:
            hours = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24, "90d": 90 * 24}[
                range_name
            ]
        except KeyError as exc:
            raise ValueError(f"unsupported time range: {range_name}") from exc
        start, label = end - timedelta(hours=hours), range_name
    if start is not None and start > end:
        raise ValueError("start time must not be later than end time")
    return TimeSelection(start=start, end=end, label=label, rolling=rolling)


def refresh_time_selection(
    selection: TimeSelection, now: datetime | None = None
) -> TimeSelection:
    if not selection.rolling:
        return selection
    now = now or datetime.now(timezone.utc)
    if selection.label == "custom":
        start = selection.start
    elif selection.label == "all":
        start = None
    elif selection.label == "today":
        local_now = now.astimezone()
        start = datetime.combine(local_now.date(), datetime_time.min, local_now.tzinfo).astimezone(
            timezone.utc
        )
    else:
        hours = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24, "90d": 90 * 24}[
            selection.label
        ]
        start = now - timedelta(hours=hours)
    return TimeSelection(start=start, end=now, label=selection.label, rolling=True)


def matches_model(model: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    candidate = model.lower()
    for raw_pattern in patterns:
        pattern = raw_pattern.lower()
        if any(character in pattern for character in "*?["):
            if fnmatch.fnmatchcase(candidate, pattern):
                return True
        elif pattern in candidate:
            return True
    return False


def _parse_boundary(value: str, *, end: bool) -> datetime:
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            local_zone = datetime.now().astimezone().tzinfo
            boundary = datetime_time.max if end else datetime_time.min
            return datetime.combine(parsed_date, boundary, local_zone).astimezone(timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO date/time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return parsed.astimezone(timezone.utc)


def _request_key(request: MeasurementRequest) -> tuple:
    paths = tuple(
        (agent.value, tuple(str(path.expanduser()) for path in values))
        for agent, values in sorted(request.custom_paths.items(), key=lambda item: item[0].value)
    )
    return (
        tuple(agent.value for agent in request.agents),
        tuple(request.models),
        request.range_name,
        request.start,
        request.end,
        request.granularity,
        paths,
        request.include_estimates,
        str(request.warehouse_file) if request.warehouse_file else None,
        str(request.state_file) if request.state_file else None,
    )
