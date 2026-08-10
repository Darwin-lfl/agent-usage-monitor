from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .analytics import GRANULARITIES
from .models import Agent
from .output import compact, csv_output, json_output, render_dashboard
from .service import (
    RANGES,
    MeasurementRequest,
    MeasurementService,
    matches_model,
    measure_adapters,
    refresh_time_selection,
    resolve_time_range,
)

DEFAULT_WAREHOUSE = Path("~/.agent-usage-monitor/usage.sqlite3")
DEFAULT_STATE = Path("~/.agent-usage-monitor/state/latest.json")
def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="agent-monitor",
        description="Analyze token usage from local coding-agent logs without uploading data.",
    )
    result.add_argument(
        "--agent",
        action="append",
        choices=[agent.value for agent in Agent],
        help="Agent to scan; repeat to select multiple (default: all).",
    )
    result.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Model substring or glob pattern; repeat to select multiple.",
    )
    result.add_argument(
        "--data-path",
        action="append",
        default=[],
        metavar="AGENT=PATH",
        help="Override an agent data path; repeat to add paths.",
    )
    result.add_argument(
        "--view", choices=("overview", "models", "timeline", "sources"), default="overview"
    )
    result.add_argument("--output", choices=("rich", "json", "csv"), default="rich")
    result.add_argument("--once", action="store_true", help="Print one snapshot and exit.")
    result.add_argument("--compact", action="store_true", help="Print a status-bar friendly line.")
    result.add_argument("--range", dest="time_range", choices=RANGES, default="7d")
    result.add_argument("--start", help="Custom local/ISO start time, for example 2026-08-01.")
    result.add_argument("--end", help="Custom local/ISO end time, for example 2026-08-08T18:00.")
    result.add_argument("--granularity", choices=GRANULARITIES, default="day")
    result.add_argument(
        "--refresh-rate",
        type=int,
        default=0,
        help="TUI refresh interval in seconds; 0 disables periodic refresh.",
    )
    result.add_argument(
        "--exact-only", action="store_true", help="Disable message-text estimates for closed IDEs."
    )
    result.add_argument(
        "--warehouse", action="store_true", help="Persist events in a local SQLite file."
    )
    result.add_argument("--warehouse-file", type=Path, default=DEFAULT_WAREHOUSE)
    result.add_argument(
        "--write-state", action="store_true", help="Atomically update a JSON state file."
    )
    result.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    result.add_argument("--doctor", action="store_true", help="Show source detection and exit.")
    result.add_argument(
        "--version", action="version", version=f"agent-usage-monitor {__version__}"
    )
    return result


def main(argv: list[str] | None = None) -> None:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    command = raw_args.pop(0) if raw_args and raw_args[0] in {"tui", "web"} else None
    if command == "web":
        _run_web(raw_args)
        return

    args = parser().parse_args(raw_args)
    try:
        custom_paths = _parse_agent_paths(args.data_path)
        _resolve_time_range(args.time_range, args.start, args.end)
    except ValueError as exc:
        parser().error(str(exc))
    agents = [Agent(value) for value in args.agent] if args.agent else None
    console = Console()
    service = MeasurementService()

    if args.once or args.output != "rich" or args.compact or args.doctor:
        events, snapshot = service.measure(
            MeasurementRequest(
                agents=agents or list(Agent),
                models=args.model,
                range_name=args.time_range,
                start=args.start,
                end=args.end,
                granularity=args.granularity,
                custom_paths=custom_paths,
                include_estimates=not args.exact_only,
                warehouse_file=args.warehouse_file if args.warehouse else None,
                state_file=args.state_file if args.write_state else None,
            )
        )
        view = "sources" if args.doctor else args.view
        if args.compact:
            console.print(compact(snapshot), markup=False)
        elif args.output == "json":
            console.print_json(json_output(snapshot))
        elif args.output == "csv":
            sys.stdout.write(csv_output(events))
        else:
            console.print(render_dashboard(snapshot, events, view, console.size.width))
        raise SystemExit(0 if snapshot["totals"]["events"] else 30)

    from .tui import UsageMonitorApp

    UsageMonitorApp(
        custom_paths=custom_paths,
        initial_agents=agents or list(Agent),
        initial_range=args.time_range,
        initial_start=args.start,
        initial_end=args.end,
        initial_granularity=args.granularity,
        initial_models=args.model,
        initial_view=args.view,
        include_estimates=not args.exact_only,
        refresh_interval=args.refresh_rate,
        warehouse_file=args.warehouse_file if args.warehouse else None,
        state_file=args.state_file if args.write_state else None,
        service=service,
    ).run()


def web_parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="agent-monitor web",
        description="Open a local browser dashboard for coding-agent token usage.",
    )
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--no-open", action="store_true", help="Do not open a browser window.")
    result.add_argument(
        "--data-path", action="append", default=[], metavar="AGENT=PATH"
    )
    result.add_argument(
        "--exact-only", action="store_true", help="Disable estimated IDE usage events."
    )
    return result


def _run_web(argv: list[str]) -> None:
    args = web_parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        web_parser().error("--port must be between 0 and 65535")
    try:
        custom_paths = _parse_agent_paths(args.data_path)
    except ValueError as exc:
        web_parser().error(str(exc))
    from .web import run_web

    run_web(
        port=args.port,
        open_browser=not args.no_open,
        custom_paths=custom_paths,
        include_estimates=not args.exact_only,
    )


def _parse_agent_paths(values: list[str]) -> dict[Agent, list[Path]]:
    result: dict[Agent, list[Path]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"invalid --data-path {value!r}; expected AGENT=PATH")
        name, raw_path = value.split("=", 1)
        try:
            agent = Agent(name.lower())
        except ValueError as exc:
            raise ValueError(f"unknown agent in --data-path: {name}") from exc
        result.setdefault(agent, []).append(Path(raw_path))
    return result


# Keep these names for existing integrations that imported the original CLI helpers.
def _resolve_time_range(*args, **kwargs):
    return resolve_time_range(*args, **kwargs)


def _refresh_time_selection(*args, **kwargs):
    return refresh_time_selection(*args, **kwargs)


def _matches_model(*args, **kwargs):
    return matches_model(*args, **kwargs)


def _measure(*args, **kwargs):
    return measure_adapters(*args, **kwargs)
