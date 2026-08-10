from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Sparkline,
    Static,
    TabbedContent,
    TabPane,
)

from .models import Agent, UsageEvent
from .output import AGENT_LABELS, format_tokens
from .service import MeasurementRequest, MeasurementService

RANGE_OPTIONS = (
    ("Today", "today"),
    ("Last 24 hours", "24h"),
    ("Last 7 days", "7d"),
    ("Last 30 days", "30d"),
    ("Last 90 days", "90d"),
    ("All time", "all"),
    ("Custom", "custom"),
)
GRANULARITY_OPTIONS = tuple((value.title(), value) for value in ("hour", "day", "week", "month"))
AGENT_OPTIONS = (("All agents", "all"),) + tuple(
    (AGENT_LABELS[agent.value], agent.value) for agent in Agent
)


@dataclass(frozen=True, slots=True)
class FilterRequest:
    agents: list[Agent]
    models: list[str]
    range_name: str
    start: str | None
    end: str | None
    granularity: str


Loader = Callable[[FilterRequest], tuple[list[UsageEvent], dict]]


class InteractiveSparkline(Sparkline):
    can_focus = True

    class BucketChanged(Message):
        def __init__(self, rows: list[dict], mode: str) -> None:
            super().__init__()
            self.rows = rows
            self.mode = mode

    def __init__(self, **kwargs) -> None:
        super().__init__([], summary_function=sum, **kwargs)
        self.buckets: list[dict] = []
        self._selected: tuple[int, int] | None = None
        self._hovered: tuple[int, int] | None = None
        self._explicitly_pinned = False

    def set_buckets(self, buckets: list[dict]) -> None:
        self.buckets = buckets
        self.data = [row["usage"]["total"] for row in buckets]
        self._hovered = None
        self._explicitly_pinned = False
        self._selected = (len(buckets) - 1, len(buckets)) if buckets else None
        self._emit_selection("latest")

    def on_mouse_move(self, event: events.MouseMove) -> None:
        selection = self._selection_at_event(event)
        if selection is None or selection == self._hovered:
            return
        self._hovered = selection
        self._emit(selection, "preview")

    def on_leave(self, _event: events.Leave) -> None:
        self._hovered = None
        self._emit_selection("pinned" if self._explicitly_pinned else "latest")

    def on_click(self, event: events.Click) -> None:
        selection = self._selection_at_event(event)
        if selection is None:
            return
        self.focus()
        self._selected = selection
        self._explicitly_pinned = True
        self._emit(selection, "pinned")
        event.stop()

    def on_key(self, event: events.Key) -> None:
        if not self.buckets or event.key not in {"left", "right", "home", "end"}:
            return
        if event.key == "home":
            index = 0
        elif event.key == "end":
            index = len(self.buckets) - 1
        else:
            start, end = self._selected or (len(self.buckets) - 1, len(self.buckets))
            index = max(0, start - 1) if event.key == "left" else min(len(self.buckets) - 1, end)
        self._selected = (index, index + 1)
        self._explicitly_pinned = True
        self._emit(self._selected, "pinned")
        event.stop()

    def _selection_at_event(self, event: events.MouseEvent) -> tuple[int, int] | None:
        offset = event.get_content_offset(self)
        count, width = len(self.buckets), self.content_size.width
        if offset is None or not count or not width:
            return None
        x = min(width - 1, max(0, offset.x))
        if count <= width:
            start = min(count - 1, int(x * count / width))
            return start, start + 1
        start = int(x * count / width)
        end = max(start + 1, int((x + 1) * count / width))
        return start, min(count, end)

    def _emit_selection(self, mode: str) -> None:
        if self._selected is not None:
            self._emit(self._selected, mode)
        else:
            self.post_message(self.BucketChanged([], mode))

    def _emit(self, selection: tuple[int, int], mode: str) -> None:
        start, end = selection
        rows = self.buckets[start:end]
        self.tooltip = _activity_tooltip(rows)
        self.post_message(self.BucketChanged(rows, mode))


class UsageMonitorApp(App[None]):
    TITLE = "Agent Usage Monitor"
    SUB_TITLE = ""
    CSS = """
    Screen {
        background: #0e1214;
        color: #e6edf3;
    }

    Header, Footer {
        background: #171d20;
        color: #e6edf3;
    }

    #toolbar {
        height: 5;
        padding: 0 1;
        background: #151a1d;
        border-bottom: solid #3a474d;
    }

    #main {
        height: 1fr;
        padding: 0 1;
    }

    .filter-field {
        height: 4;
        margin-right: 1;
    }

    .filter-label {
        height: 1;
        color: #9ba7ad;
    }

    #agent-field {
        width: 15;
    }

    #range-field {
        width: 18;
    }

    #granularity-field {
        width: 13;
    }

    #model-field {
        width: 1fr;
        min-width: 16;
    }

    .filter-field Select {
        width: 1fr;
    }

    #refresh {
        width: 5;
        min-width: 5;
        height: 3;
        margin-top: 1;
    }

    #custom-dates {
        display: none;
        height: 3;
        padding: 0 1;
        background: #151a1d;
        border-bottom: solid #3a474d;
    }

    #custom-dates.visible {
        display: block;
    }

    #custom-dates Label {
        width: 14;
        content-align: left middle;
        color: #9ba7ad;
    }

    #custom-dates Input {
        width: 1fr;
        margin-right: 1;
    }

    #summary {
        height: 5;
        padding: 1 1 0 1;
        border-bottom: solid #354147;
    }

    #activity-block {
        height: 5;
    }

    #activity-row {
        height: 3;
        padding: 0 1;
    }

    #activity-label {
        width: 18;
        content-align: left middle;
        color: #9ba7ad;
    }

    #activity {
        width: 1fr;
        height: 3;
        color: #56b6c2;
    }

    #load-status {
        width: 28;
        content-align: right middle;
        color: #aab4b9;
    }

    #activity-detail {
        height: 2;
        padding: 0 1;
        color: #c8d1d6;
        overflow: hidden hidden;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 0;
    }

    DataTable {
        height: 1fr;
        background: #101517;
        border: solid #303a3f;
    }

    #model-detail {
        height: 4;
        padding: 1;
        background: #171d20;
        border-top: solid #354147;
        color: #c8d1d6;
    }

    .compact #toolbar {
        height: 4;
    }

    .compact #summary {
        height: 3;
        padding: 0 1;
    }

    .compact #activity-block {
        height: 4;
    }

    .compact #activity-row {
        height: 2;
    }

    .compact #activity-label {
        width: 10;
    }

    .compact #activity {
        height: 1;
    }

    .compact #load-status {
        width: 13;
    }

    .compact #model-detail {
        display: none;
    }

    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("1", "show_tab('overview')", "Agents"),
        ("2", "show_tab('models')", "Models"),
        ("3", "show_tab('timeline')", "Timeline"),
        ("4", "show_tab('sources')", "Sources"),
    ]

    def __init__(
        self,
        *,
        custom_paths: dict[Agent, list[Path]] | None = None,
        initial_agents: list[Agent] | None = None,
        initial_range: str = "7d",
        initial_start: str | None = None,
        initial_end: str | None = None,
        initial_granularity: str = "day",
        initial_models: list[str] | None = None,
        initial_view: str = "overview",
        include_estimates: bool = True,
        refresh_interval: int = 0,
        warehouse_file: Path | None = None,
        state_file: Path | None = None,
        loader: Loader | None = None,
        service: MeasurementService | None = None,
        enable_periodic_refresh: bool = True,
    ) -> None:
        super().__init__()
        self.custom_paths = custom_paths or {}
        self.initial_agents = initial_agents or list(Agent)
        self.initial_range = initial_range
        self.initial_start = initial_start
        self.initial_end = initial_end
        self.initial_granularity = initial_granularity
        self.initial_models = initial_models or []
        self.initial_view = initial_view
        self.include_estimates = include_estimates
        self.refresh_interval = max(0, min(refresh_interval, 3600))
        self.warehouse_file = warehouse_file
        self.state_file = state_file
        self.loader = loader or self._load_request
        self.service = service or MeasurementService()
        self.enable_periodic_refresh = enable_periodic_refresh
        self._known_models: set[str] = set()
        self._model_rows: dict[str, dict] = {}
        self._last_request: FilterRequest | None = None
        self._controls_ready = False
        self._updating_models = False
        self._filter_timer = None
        self._periodic_timer = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="")
        with Horizontal(id="toolbar"):
            with Vertical(id="agent-field", classes="filter-field"):
                yield Label("Agent", classes="filter-label")
                yield Select(
                    AGENT_OPTIONS,
                    value=(
                        self.initial_agents[0].value
                        if len(self.initial_agents) == 1
                        else "all"
                    ),
                    allow_blank=False,
                    compact=True,
                    id="agent-filter",
                )
            with Vertical(id="range-field", classes="filter-field"):
                yield Label("Range", classes="filter-label")
                yield Select(
                    RANGE_OPTIONS,
                    value=self.initial_range,
                    allow_blank=False,
                    compact=True,
                    id="range-filter",
                )
            with Vertical(id="granularity-field", classes="filter-field"):
                yield Label("Group", classes="filter-label")
                yield Select(
                    GRANULARITY_OPTIONS,
                    value=self.initial_granularity,
                    allow_blank=False,
                    compact=True,
                    id="granularity-filter",
                )
            with Vertical(id="model-field", classes="filter-field"):
                yield Label("Model", classes="filter-label")
                yield Select(
                    (("All models", "all"),),
                    value="all",
                    allow_blank=False,
                    compact=True,
                    id="model-filter",
                )
            yield Button("↻", id="refresh", tooltip="Scan local usage data again")
        with Horizontal(id="custom-dates"):
            yield Label("Custom range")
            yield Input(
                value=self.initial_start or "",
                placeholder="Start: YYYY-MM-DD",
                id="start-filter",
            )
            yield Input(
                value=self.initial_end or "",
                placeholder="End: optional",
                id="end-filter",
            )
        with Vertical(id="main"):
            yield Static(id="summary")
            with Vertical(id="activity-block"):
                with Horizontal(id="activity-row"):
                    yield Label("Token activity", id="activity-label")
                    yield InteractiveSparkline(
                        min_color="#33434a", max_color="#56b6c2", id="activity"
                    )
                    yield Static("Waiting for data", id="load-status")
                yield Static("No activity in the selected range.", id="activity-detail")
            with TabbedContent(initial=self.initial_view, id="views"):
                with TabPane("Agents", id="overview"):
                    yield DataTable(id="agents-table", zebra_stripes=True, cursor_type="row")
                with TabPane("Models", id="models"):
                    yield DataTable(id="models-table", zebra_stripes=True, cursor_type="row")
                    yield Static("Select a model row for details.", id="model-detail")
                with TabPane("Timeline", id="timeline"):
                    yield DataTable(id="timeline-table", zebra_stripes=True, cursor_type="row")
                with TabPane("Sources", id="sources"):
                    yield DataTable(id="sources-table", zebra_stripes=True, cursor_type="row")
        yield Footer(show_command_palette=False, compact=True)

    def on_mount(self) -> None:
        self._configure_tables()
        self._sync_custom_dates()
        self._start_load(self._request_from_widgets(models=self.initial_models))
        self.call_after_refresh(self._enable_controls)
        if self.enable_periodic_refresh and self.refresh_interval:
            self._periodic_timer = self.set_interval(
                self.refresh_interval, self.action_refresh
            )

    def _enable_controls(self) -> None:
        self._controls_ready = True

    def on_resize(self, event: events.Resize) -> None:
        compact = event.size.width < 100 or event.size.height < 30
        self.set_class(compact, "compact")
        label = self.query_one("#activity-label", Label)
        label.update("Activity" if compact else "Token activity")

    def _configure_tables(self) -> None:
        self.query_one("#agents-table", DataTable).add_columns(
            "Agent", "Total", "Input", "Output", "Cache", "Models", "Events", "Quality"
        )
        self.query_one("#models-table", DataTable).add_columns(
            "Model", "Total", "Input", "Output", "Cache", "Events", "Agent", "Share", "Cost"
        )
        self.query_one("#timeline-table", DataTable).add_columns(
            "Period", "Total", "Input", "Output", "Cache", "Events", "Top model", "Models"
        )
        self.query_one("#sources-table", DataTable).add_columns(
            "Agent", "State", "Files", "Records", "Parsed", "Path / error"
        )

    def _request_from_widgets(self, *, models: list[str] | None = None) -> FilterRequest:
        agent_value = str(self.query_one("#agent-filter", Select).value)
        model_value = str(self.query_one("#model-filter", Select).value)
        selected_models = models if models is not None else (
            [] if model_value == "all" else [model_value]
        )
        return FilterRequest(
            agents=list(Agent) if agent_value == "all" else [Agent(agent_value)],
            models=list(selected_models),
            range_name=str(self.query_one("#range-filter", Select).value),
            start=self.query_one("#start-filter", Input).value.strip() or None,
            end=self.query_one("#end-filter", Input).value.strip() or None,
            granularity=str(self.query_one("#granularity-filter", Select).value),
        )

    def _start_load(self, request: FilterRequest) -> None:
        if not request.agents:
            self.notify("Select at least one agent.", severity="warning")
            return
        self._last_request = request
        self.query_one("#load-status", Static).update("Scanning local logs...")
        self._load_worker(request)

    @work(thread=True, exclusive=True, group="usage-data")
    def _load_worker(self, request: FilterRequest) -> None:
        try:
            events, snapshot = self.loader(request)
        except Exception as exc:  # Textual surfaces the error without ending the app.
            self.call_from_thread(self._load_failed, str(exc))
        else:
            self.call_from_thread(self._apply_snapshot, events, snapshot)

    def _load_request(self, request: FilterRequest) -> tuple[list[UsageEvent], dict]:
        return self.service.measure(
            MeasurementRequest(
                agents=request.agents,
                models=request.models,
                range_name=request.range_name,
                start=request.start,
                end=request.end,
                granularity=request.granularity,
                custom_paths=self.custom_paths,
                include_estimates=self.include_estimates,
                warehouse_file=self.warehouse_file,
                state_file=self.state_file,
            )
        )

    def _load_failed(self, message: str) -> None:
        self.query_one("#load-status", Static).update("Load failed")
        self.notify(message, title="Unable to load usage", severity="error", timeout=8)

    def _apply_snapshot(self, events: list[UsageEvent], snapshot: dict) -> None:
        self._update_summary(snapshot)
        self._update_agents(snapshot)
        self._update_models(snapshot)
        self._update_timeline(snapshot)
        self._update_sources(snapshot)
        self._add_discovered_models(snapshot)
        self.query_one("#activity", InteractiveSparkline).set_buckets(snapshot["timeline"])
        updated = datetime.now().astimezone().strftime("%H:%M")
        self.query_one("#load-status", Static).update(f"Updated {updated}")
        for warning in snapshot["warnings"]:
            if "No usage" not in warning:
                self.notify(warning, severity="warning", timeout=6)

    def _update_summary(self, snapshot: dict) -> None:
        totals = snapshot["totals"]
        cost = totals["cost_usd"]
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_row(
            _metric("TOTAL TOKENS", format_tokens(totals["usage"]["total"]), "bold cyan"),
            _metric("MODELS", str(len(snapshot["models"])), "bold white"),
            _metric("EVENTS", f"{totals['events']:,}", "bold white"),
            _metric("LOGGED COST", f"${cost:,.2f}" if cost else "not reported", "bold green"),
        )
        self.query_one("#summary", Static).update(table)

    def on_interactive_sparkline_bucket_changed(
        self, event: InteractiveSparkline.BucketChanged
    ) -> None:
        self.query_one("#activity-detail", Static).update(
            _activity_detail(event.rows, event.mode)
        )

    def _update_agents(self, snapshot: dict) -> None:
        table = self.query_one("#agents-table", DataTable)
        table.clear()
        selected = {source["agent"] for source in snapshot["sources"]}
        for name, row in snapshot["agents"].items():
            if name not in selected:
                continue
            usage = row["usage"]
            quality = "estimated" if row["estimated_events"] else "exact" if row["events"] else "-"
            table.add_row(
                AGENT_LABELS[name],
                format_tokens(usage["total"]),
                format_tokens(usage["input"]),
                format_tokens(usage["output"]),
                format_tokens(usage["cache_read"] + usage["cache_write"]),
                str(len(row["models"])),
                f"{row['events']:,}",
                quality,
                key=name,
            )

    def _update_models(self, snapshot: dict) -> None:
        table = self.query_one("#models-table", DataTable)
        table.clear()
        self._model_rows.clear()
        for index, row in enumerate(snapshot["models"]):
            usage = row["usage"]
            key = f"model-{index}"
            self._model_rows[key] = row
            table.add_row(
                row["model"],
                format_tokens(usage["total"]),
                format_tokens(usage["input"]),
                format_tokens(usage["output"]),
                format_tokens(usage["cache_read"] + usage["cache_write"]),
                f"{row['events']:,}",
                AGENT_LABELS[row["agent"]],
                f"{row['share']:.1f}%",
                f"${row['cost_usd']:,.2f}" if row["cost_usd"] else "-",
                key=key,
            )
        if snapshot["models"]:
            self._show_model_detail(snapshot["models"][0])
        else:
            self.query_one("#model-detail", Static).update("No model usage matches the filters.")

    def _update_timeline(self, snapshot: dict) -> None:
        table = self.query_one("#timeline-table", DataTable)
        table.clear()
        for row in snapshot["timeline"]:
            usage = row["usage"]
            breakdown = row["model_breakdown"]
            table.add_row(
                row["period"],
                format_tokens(usage["total"]),
                format_tokens(usage["input"]),
                format_tokens(usage["output"]),
                format_tokens(usage["cache_read"] + usage["cache_write"]),
                f"{row['events']:,}",
                breakdown[0]["model"] if breakdown else "-",
                str(len(breakdown)),
                key=row["period"],
            )

    def _update_sources(self, snapshot: dict) -> None:
        table = self.query_one("#sources-table", DataTable)
        table.clear()
        for source in snapshot["sources"]:
            if source["errors"]:
                state = "error"
            elif source["events"]:
                state = "collecting"
            elif source["available"]:
                state = "detected"
            else:
                state = "not found"
            details = "; ".join(source["errors"][:1]) or ", ".join(source["paths"][:2])
            table.add_row(
                AGENT_LABELS[source["agent"]],
                state,
                str(source["files_scanned"]),
                str(source["records_read"]),
                str(source["events"]),
                details,
                key=source["agent"],
            )

    def _add_discovered_models(self, snapshot: dict) -> None:
        choices = self.query_one("#model-filter", Select)
        current = str(choices.value)
        discovered = {row["model"] for row in snapshot["models"]}
        if not snapshot["selection"]["models"]:
            self._known_models = discovered
        elif not self._known_models:
            self._known_models = discovered
        options = (("All models", "all"),) + tuple(
            (model, model) for model in sorted(self._known_models)
        )
        self._updating_models = True
        choices.set_options(options)
        desired = current if current in self._known_models or current == "all" else "all"
        if len(self.initial_models) == 1 and self.initial_models[0] in self._known_models:
            desired = self.initial_models[0]
            self.initial_models = []
        choices.value = desired
        self._updating_models = False

    def _show_model_detail(self, row: dict) -> None:
        usage = row["usage"]
        text = Text(row["model"], style="bold cyan")
        text.append(
            f"  {AGENT_LABELS[row['agent']]}  |  {row['share']:.1f}% of selected usage\n",
            style="dim",
        )
        text.append(
            f"Input {format_tokens(usage['input'])}   Output {format_tokens(usage['output'])}   "
            f"Cache {format_tokens(usage['cache_read'] + usage['cache_write'])}   "
            f"Total {format_tokens(usage['total'])}   Events {row['events']:,}"
        )
        self.query_one("#model-detail", Static).update(text)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_highlighted_model(event.data_table, event.row_key.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_highlighted_model(event.data_table, event.row_key.value)

    def _update_highlighted_model(self, table: DataTable, row_key: object) -> None:
        if table.id != "models-table":
            return
        row = self._model_rows.get(str(row_key))
        if row:
            self._show_model_detail(row)

    def on_select_changed(self, event: Select.Changed) -> None:
        if self._controls_ready and event.select.id in {"agent-filter", "range-filter"}:
            self._clear_model_context()
        if event.select.id == "range-filter":
            self._sync_custom_dates()
            if event.value == "custom":
                self.query_one("#start-filter", Input).focus()
                return
        if self._controls_ready and not self._updating_models:
            if (
                self.query_one("#range-filter", Select).value == "custom"
                and not self.query_one("#start-filter", Input).value.strip()
            ):
                return
            if self._filter_timer is not None:
                self._filter_timer.stop()
            self._filter_timer = self.set_timer(0.2, self._apply_current_filters)

    def _clear_model_context(self) -> None:
        self._known_models.clear()
        choices = self.query_one("#model-filter", Select)
        self._updating_models = True
        choices.set_options((("All models", "all"),))
        choices.value = "all"
        self._updating_models = False

    def _apply_current_filters(self) -> None:
        self._filter_timer = None
        self._start_load(self._request_from_widgets())

    def _sync_custom_dates(self) -> None:
        custom = self.query_one("#range-filter", Select).value == "custom"
        self.query_one("#custom-dates").set_class(custom, "visible")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh":
            self.action_refresh()

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        if self._filter_timer is not None:
            self._filter_timer.stop()
            self._filter_timer = None
        self._start_load(self._request_from_widgets())

    def action_refresh(self) -> None:
        if self._last_request is not None:
            self._start_load(self._last_request)

    def action_show_tab(self, tab: str) -> None:
        self.query_one("#views", TabbedContent).active = tab


def _activity_summary(rows: list[dict]) -> dict:
    if not rows:
        return {}
    usage = {
        key: sum(row["usage"][key] for row in rows)
        for key in ("input", "output", "cache_read", "cache_write", "total")
    }
    models: dict[str, int] = {}
    for row in rows:
        for model in row["model_breakdown"]:
            name = model["model"]
            models[name] = models.get(name, 0) + model["usage"]["total"]
    top_model = max(models, key=models.get) if models else "-"
    period = rows[0]["period"]
    if len(rows) > 1:
        period = f"{period} - {rows[-1]['period']}"
    return {
        "period": period,
        "usage": usage,
        "events": sum(row["events"] for row in rows),
        "top_model": top_model,
    }


def _activity_detail(rows: list[dict], mode: str) -> Text:
    summary = _activity_summary(rows)
    if not summary:
        return Text("No activity in the selected range.", style="dim")
    usage = summary["usage"]
    model = summary["top_model"]
    display_model = model if len(model) <= 36 else model[:33] + "..."
    label_style = "green" if mode == "pinned" else "cyan" if mode == "preview" else "dim"
    text = Text(mode.upper() + "  ", style=label_style)
    text.append(summary["period"], style="bold cyan")
    text.append(
        f"  Total {format_tokens(usage['total'])}  Events {summary['events']:,}  "
        f"Top {display_model}\n"
    )
    text.append(
        f"Input {format_tokens(usage['input'])}  Output {format_tokens(usage['output'])}  "
        f"Cache {format_tokens(usage['cache_read'] + usage['cache_write'])}",
        style="dim",
    )
    return text


def _activity_tooltip(rows: list[dict]) -> str:
    summary = _activity_summary(rows)
    if not summary:
        return "No activity in the selected range"
    usage = summary["usage"]
    return (
        f"{summary['period']}\n"
        f"Total {format_tokens(usage['total'])} | Input {format_tokens(usage['input'])} | "
        f"Output {format_tokens(usage['output'])} | "
        f"Cache {format_tokens(usage['cache_read'] + usage['cache_write'])}\n"
        f"{summary['events']:,} events | Top model: {summary['top_model']}"
    )


def _metric(label: str, value: str, style: str) -> Text:
    result = Text(label, style="dim")
    result.append("\n" + value, style=style)
    return result
