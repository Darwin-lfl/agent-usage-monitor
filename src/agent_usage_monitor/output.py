from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import UsageEvent

AGENT_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "opencode": "OpenCode",
    "trae": "Trae",
    "qoder": "Qoder",
    "codebuddy": "CodeBuddy",
}
BLOCKS = "▁▂▃▄▅▆▇█"


def render_dashboard(
    snapshot: dict,
    events: list[UsageEvent],
    view: str = "overview",
    width: int = 100,
) -> Group:
    sections: list[RenderableType] = [
        _header(snapshot, view),
        _metric_strip(snapshot, events, width),
    ]
    alerts = _alerts(snapshot)
    if alerts:
        sections.append(alerts)

    if view == "models":
        sections.append(_models_table(snapshot, width, detailed=True))
    elif view == "timeline":
        sections.append(_timeline_table(snapshot, width))
    elif view == "sources":
        sections.append(_sources_table(snapshot, width))
    else:
        sections.append(_models_table(snapshot, width, detailed=False))
        sections.append(_agents_table(snapshot, width))
        sections.append(_timeline_table(snapshot, width, limit=12))
        sections.append(_source_line(snapshot))

    sections.append(_footer(snapshot))
    return Group(*sections)


def _header(snapshot: dict, view: str) -> Panel:
    selection = snapshot["selection"]
    grid = Table.grid(expand=True)
    grid.add_column(ratio=1)
    grid.add_column(justify="right")
    title = Text("AGENT USAGE", style="bold white")
    title.append("  ANALYTICS", style="bold bright_cyan")
    title.append("  v0.1", style="dim")
    range_text = selection["range"]
    if range_text == "custom":
        range_text = f"{_local_time(selection['start'])} → {_local_time(selection['end'])}"
    context = f"{range_text}  •  {selection['granularity']}  •  {view}"
    grid.add_row(title, Text(context.upper(), style="dim green"))
    if selection["models"]:
        grid.add_row(Text(), Text("MODELS: " + ", ".join(selection["models"]), style="cyan"))
    return Panel(grid, border_style="bright_cyan", padding=(0, 1))


def _metric_strip(snapshot: dict, events: list[UsageEvent], width: int) -> Panel:
    totals = snapshot["totals"]
    cost = totals["cost_usd"]
    metrics = [
        ("TOTAL TOKENS", format_tokens(totals["usage"]["total"]), "bold bright_cyan"),
        ("MODELS", str(len(snapshot["models"])), "bold white"),
        ("EVENTS", f"{totals['events']:,}", "bold white"),
        (
            "LOGGED COST",
            f"${cost:,.2f}" if cost else "not reported",
            "bold green" if cost else "dim",
        ),
    ]
    table = Table.grid(expand=True, padding=(0, 1))
    for _ in metrics:
        table.add_column(ratio=1)
    cells: list[Text] = []
    for label, value, style in metrics:
        cell = Text(label, style="dim")
        cell.append("\n" + value, style=style)
        cells.append(cell)
    table.add_row(*cells)
    trend = Text("ACTIVITY  ", style="dim")
    trend.append(_sparkline(events, min(36, max(12, width // 4))), style="bright_cyan")
    trend.append("  oldest → latest", style="dim")
    return Panel(Group(table, trend), border_style="grey37", padding=(0, 1))


def _alerts(snapshot: dict) -> Panel | None:
    meaningful = [warning for warning in snapshot["warnings"] if "No usage" not in warning]
    if not meaningful:
        return None
    text = Text("  •  ".join(meaningful), style="yellow")
    return Panel(text, title="DATA QUALITY", title_align="left", border_style="yellow")


def _models_table(snapshot: dict, width: int, *, detailed: bool) -> Panel:
    rows = snapshot["models"] if detailed else snapshot["models"][:8]
    table = Table(box=None, expand=True, padding=(0, 1))
    table.add_column("Model", ratio=2, overflow="ellipsis")
    if width >= 92:
        table.add_column("Agent", no_wrap=True)
    if detailed and width >= 108:
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cache", justify="right")
    table.add_column("Total", justify="right", no_wrap=True)
    table.add_column("Events", justify="right", no_wrap=True)
    table.add_column("Share", ratio=2)
    largest = max((row["usage"]["total"] for row in rows), default=0)
    for row in rows:
        usage = row["usage"]
        values: list[RenderableType] = [Text(row["model"])]
        if width >= 92:
            values.append(Text(AGENT_LABELS[row["agent"]], style="dim"))
        if detailed and width >= 108:
            values.extend(
                [
                    Text(format_tokens(usage["input"])),
                    Text(format_tokens(usage["output"])),
                    Text(format_tokens(usage["cache_read"] + usage["cache_write"])),
                ]
            )
        values.extend(
            [
                Text(format_tokens(usage["total"]), style="bold bright_cyan"),
                Text(f"{row['events']:,}"),
                _share_bar(row["share"], usage["total"], largest, width),
            ]
        )
        table.add_row(*values)
    if not rows:
        table.add_row(Text("No model usage for the selected filters.", style="dim"))
    return Panel(table, title="MODEL STATISTICS", title_align="left", border_style="cyan")


def _share_bar(share: float, value: int, largest: int, width: int) -> Text:
    bar_width = max(6, min(18, width // 8))
    filled = round(value / largest * bar_width) if largest else 0
    text = Text("━" * filled, style="bright_cyan")
    text.append("╺" * (bar_width - filled), style="grey23")
    text.append(f" {share:.1f}%", style="dim")
    return text


def _timeline_table(snapshot: dict, width: int, limit: int | None = None) -> Panel:
    all_rows = snapshot["timeline"]
    display_limit = limit or 50
    rows = all_rows[-display_limit:]
    table = Table(box=None, expand=True, padding=(0, 1))
    table.add_column("Period", no_wrap=True)
    if width >= 92:
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cache", justify="right")
    table.add_column("Total", justify="right", style="bright_cyan")
    table.add_column("Events", justify="right")
    table.add_column("Top model", ratio=2, overflow="ellipsis")
    for row in rows:
        usage = row["usage"]
        top_model = row["model_breakdown"][0]["model"] if row["model_breakdown"] else "—"
        values: list[RenderableType] = [Text(row["period"])]
        if width >= 92:
            values.extend(
                [
                    Text(format_tokens(usage["input"])),
                    Text(format_tokens(usage["output"])),
                    Text(format_tokens(usage["cache_read"] + usage["cache_write"])),
                ]
            )
        values.extend(
            [
                Text(format_tokens(usage["total"]), style="bold bright_cyan"),
                Text(f"{row['events']:,}"),
                Text(top_model, style="dim"),
            ]
        )
        table.add_row(*values)
    if not rows:
        table.add_row(Text("No time buckets for the selected filters.", style="dim"))
    title = f"USAGE BY {snapshot['selection']['granularity'].upper()}"
    if len(all_rows) > len(rows):
        title += f"  •  LAST {len(rows)} OF {len(all_rows)}"
    return Panel(table, title=title, title_align="left", border_style="grey37")


def _agents_table(snapshot: dict, width: int) -> Panel:
    selected_agents = {source["agent"] for source in snapshot["sources"]}
    table = Table(box=None, expand=True, padding=(0, 1))
    table.add_column("Agent", style="bold")
    if width >= 100:
        table.add_column("Input", justify="right")
        table.add_column("Output", justify="right")
        table.add_column("Cache", justify="right")
    table.add_column("Total", justify="right", style="bright_cyan")
    table.add_column("Models", justify="right")
    table.add_column("Events", justify="right")
    table.add_column("Quality", justify="right")
    for name, data in snapshot["agents"].items():
        if name not in selected_agents and not data["events"]:
            continue
        usage = data["usage"]
        values: list[RenderableType] = [Text(AGENT_LABELS[name])]
        if width >= 100:
            values.extend(
                [
                    Text(format_tokens(usage["input"])),
                    Text(format_tokens(usage["output"])),
                    Text(format_tokens(usage["cache_read"] + usage["cache_write"])),
                ]
            )
        quality = "estimated" if data["estimated_events"] else "exact" if data["events"] else "—"
        values.extend(
            [
                Text(format_tokens(usage["total"])),
                Text(str(len(data["models"]))),
                Text(f"{data['events']:,}"),
                Text(quality, style="green" if quality == "exact" else "yellow"),
            ]
        )
        table.add_row(*values)
    return Panel(table, title="AGENT STATISTICS", title_align="left", border_style="grey37")


def _sources_table(snapshot: dict, width: int) -> Panel:
    table = Table(box=None, expand=True, padding=(0, 1))
    table.add_column("Source", style="bold")
    table.add_column("Status")
    table.add_column("Files", justify="right")
    table.add_column("Records", justify="right")
    table.add_column("Parsed", justify="right")
    if width >= 100:
        table.add_column("Path / error", ratio=2, overflow="fold")
    for source in snapshot["sources"]:
        if source["errors"]:
            state = Text("▲ error", style="yellow")
        elif source["events"]:
            state = Text("● collecting", style="green")
        elif source["available"]:
            state = Text("○ detected", style="cyan")
        else:
            state = Text("· not found", style="dim")
        values: list[RenderableType] = [
            Text(AGENT_LABELS[source["agent"]]),
            state,
            Text(str(source["files_scanned"])),
            Text(str(source["records_read"])),
            Text(str(source["events"])),
        ]
        if width >= 100:
            details = "; ".join(source["errors"][:1]) or ", ".join(source["paths"][:2])
            values.append(Text(details, style="dim"))
        table.add_row(*values)
    return Panel(table, title="SOURCE HEALTH", title_align="left", border_style="grey37")


def _source_line(snapshot: dict) -> Panel:
    text = Text()
    for index, source in enumerate(snapshot["sources"]):
        if index:
            text.append("   ")
        icon, style = ("●", "green") if source["events"] else ("○", "cyan")
        text.append(f"{icon} {AGENT_LABELS[source['agent']]}", style=style)
        text.append(f" {source['events']} parsed", style="dim")
    return Panel(text, border_style="grey23", padding=(0, 1))


def _footer(snapshot: dict) -> Text:
    totals = snapshot["totals"]
    observed = snapshot["observed_range"]
    coverage = (
        f"{_local_time(observed['start'])} → {_local_time(observed['end'])}"
        if observed["start"]
        else "no matching data"
    )
    return Text(
        f"  {totals['events']:,} events  •  exact {totals['exact_events']:,}  •  "
        f"estimated {totals['estimated_events']:,}  •  observed {coverage}",
        style="dim",
    )


def _sparkline(events: list[UsageEvent], buckets: int) -> str:
    if not events:
        return "·" * buckets
    start = min(event.timestamp for event in events).timestamp()
    end = max(event.timestamp for event in events).timestamp()
    span = max(1.0, end - start)
    values = [0] * buckets
    for event in events:
        index = min(buckets - 1, int((event.timestamp.timestamp() - start) / span * buckets))
        values[index] += event.usage.total
    peak = max(values)
    return "".join(BLOCKS[min(7, round(value / peak * 7))] for value in values)


def _local_time(value: str | None) -> str:
    if not value:
        return "—"
    return datetime.fromisoformat(value).astimezone().strftime("%m-%d %H:%M")


def compact(snapshot: dict) -> str:
    models = snapshot["models"][:3]
    body = " | ".join(f"{row['model']} {format_tokens(row['usage']['total'])}" for row in models)
    return body or "No model usage data"


def json_output(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=2)


def csv_output(events: list[UsageEvent]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(
        [
            "timestamp",
            "agent",
            "session",
            "model",
            "input",
            "output",
            "cache_read",
            "cache_write",
            "reasoning",
            "total",
            "cost_usd",
            "accuracy",
        ]
    )
    for event in events:
        writer.writerow(
            [
                event.timestamp.isoformat(),
                event.agent.value,
                event.session_id,
                event.model,
                event.usage.input,
                event.usage.output,
                event.usage.cache_read,
                event.usage.cache_write,
                event.usage.reasoning,
                event.usage.total,
                event.cost_usd if event.cost_usd is not None else "",
                event.accuracy.value,
            ]
        )
    return stream.getvalue()


def write_state(path: Path, snapshot: dict) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json_output(snapshot) + "\n", encoding="utf-8")
    temporary.replace(path)


def format_tokens(value: int) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K"
    return str(value)
