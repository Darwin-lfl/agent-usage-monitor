import asyncio
from datetime import datetime, timedelta, timezone

from textual.widgets import DataTable, Input, Select, Static, TabbedContent

from agent_usage_monitor.models import Agent, SourceStatus, TokenUsage, UsageEvent
from agent_usage_monitor.snapshot import build_snapshot
from agent_usage_monitor.tui import FilterRequest, InteractiveSparkline, UsageMonitorApp


def _fixture_loader(requests: list[FilterRequest]):
    event = UsageEvent(
        id="opencode-message",
        agent=Agent.OPENCODE,
        timestamp=datetime.now(timezone.utc),
        usage=TokenUsage(input=120_000, output=8_000, cache_read=40_000),
        model="openai/gpt-5",
    )
    status = SourceStatus(
        agent=Agent.OPENCODE,
        paths=["/local/opencode.db"],
        files_scanned=1,
        records_read=1,
        events=1,
    )

    def load(request: FilterRequest):
        requests.append(request)
        snapshot = build_snapshot(
            [event],
            [status],
            granularity=request.granularity,
            range_label=request.range_name,
            model_filters=request.models,
        )
        return [event], snapshot

    return load


def test_tui_loads_tables_and_keyboard_tabs():
    async def run():
        requests: list[FilterRequest] = []
        app = UsageMonitorApp(
            loader=_fixture_loader(requests), enable_periodic_refresh=False
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            assert app.query_one("#models-table", DataTable).row_count == 1
            assert app.query_one("#agents-table", DataTable).row_count == 1
            assert app.query_one("#model-filter", Select).value == "all"
            assert requests[0].agents == list(Agent)
            assert app._periodic_timer is None
            assert app.has_class("compact")

            await pilot.press("2")
            assert app.query_one("#views", TabbedContent).active == "models"
            assert app.query_one("#models-table", DataTable).region.height >= 8

    asyncio.run(run())


def test_tui_applies_agent_model_and_time_filters():
    async def run():
        requests: list[FilterRequest] = []
        app = UsageMonitorApp(
            loader=_fixture_loader(requests), enable_periodic_refresh=False
        )
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()

            app.query_one("#agent-filter", Select).value = Agent.OPENCODE.value
            await pilot.pause(0.3)
            await app.workers.wait_for_complete()
            assert requests[-1].agents == [Agent.OPENCODE]

            app.query_one("#range-filter", Select).value = "custom"
            await pilot.pause()
            app.query_one("#start-filter", Input).value = "2026-08-01"
            app.query_one("#end-filter", Input).value = "2026-08-08"
            app.query_one("#granularity-filter", Select).value = "hour"
            app.query_one("#end-filter", Input).focus()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            app.query_one("#model-filter", Select).value = "openai/gpt-5"
            await pilot.pause(0.3)
            await app.workers.wait_for_complete()

            request = requests[-1]
            assert request.agents == [Agent.OPENCODE]
            assert request.models == ["openai/gpt-5"]
            assert request.range_name == "custom"
            assert request.start == "2026-08-01"
            assert request.end == "2026-08-08"
            assert request.granularity == "hour"

    asyncio.run(run())


def test_agent_change_rebuilds_model_options():
    async def run():
        now = datetime.now(timezone.utc)
        events = [
            UsageEvent(
                id="open",
                agent=Agent.OPENCODE,
                timestamp=now,
                usage=TokenUsage(input=10),
                model="openai/gpt-5",
            ),
            UsageEvent(
                id="claude",
                agent=Agent.CLAUDE,
                timestamp=now,
                usage=TokenUsage(input=20),
                model="anthropic/sonnet",
            ),
        ]

        def load(request: FilterRequest):
            selected = [event for event in events if event.agent in request.agents]
            statuses = [
                SourceStatus(agent=agent, paths=[f"/{agent.value}"])
                for agent in request.agents
            ]
            return selected, build_snapshot(
                selected,
                statuses,
                granularity=request.granularity,
                range_label=request.range_name,
                model_filters=request.models,
            )

        app = UsageMonitorApp(loader=load, enable_periodic_refresh=False)
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            model_filter = app.query_one("#model-filter", Select)
            assert len(model_filter._options) == 3

            app.query_one("#agent-filter", Select).value = Agent.OPENCODE.value
            await pilot.pause(0.3)
            await app.workers.wait_for_complete()

            assert len(model_filter._options) == 2
            assert {value for _, value in model_filter._options} == {
                "all",
                "openai/gpt-5",
            }

    asyncio.run(run())


def test_model_cursor_updates_detail_without_enter():
    async def run():
        now = datetime.now(timezone.utc)
        events = [
            UsageEvent(
                id="large",
                agent=Agent.OPENCODE,
                timestamp=now,
                usage=TokenUsage(input=200),
                model="openai/gpt-5",
            ),
            UsageEvent(
                id="small",
                agent=Agent.OPENCODE,
                timestamp=now,
                usage=TokenUsage(input=100),
                model="anthropic/sonnet",
            ),
        ]
        status = SourceStatus(agent=Agent.OPENCODE, paths=["/opencode"])

        def load(request: FilterRequest):
            return events, build_snapshot(
                events,
                [status],
                granularity=request.granularity,
                range_label=request.range_name,
            )

        app = UsageMonitorApp(
            loader=load,
            initial_view="models",
            enable_periodic_refresh=False,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#models-table", DataTable)
            table.focus()
            await pilot.press("down")

            detail = str(app.query_one("#model-detail", Static).render())
            assert "anthropic/sonnet" in detail

    asyncio.run(run())


def test_activity_hover_click_and_keyboard_show_bucket_details():
    async def run():
        start = datetime(2026, 8, 8, 8, tzinfo=timezone.utc)
        events = [
            UsageEvent(
                id=f"bucket-{index}",
                agent=Agent.OPENCODE,
                timestamp=start + timedelta(hours=index),
                usage=TokenUsage(input=(index + 1) * 100, output=10),
                model=f"model-{index}",
            )
            for index in range(3)
        ]
        status = SourceStatus(agent=Agent.OPENCODE, paths=["/opencode"])
        snapshot = build_snapshot(events, [status], granularity="hour", range_label="24h")

        def load(_request: FilterRequest):
            return events, snapshot

        app = UsageMonitorApp(loader=load, enable_periodic_refresh=False)
        async with app.run_test(size=(120, 40), tooltips=True) as pilot:
            await app.workers.wait_for_complete()
            await pilot.pause()
            detail = app.query_one("#activity-detail", Static)
            activity = app.query_one("#activity", InteractiveSparkline)

            assert "LATEST" in str(detail.render())
            assert snapshot["timeline"][-1]["period"] in str(detail.render())

            await pilot.hover(activity, offset=(1, 0))
            await pilot.pause()
            assert "PREVIEW" in str(detail.render())
            assert snapshot["timeline"][0]["period"] in str(detail.render())

            await pilot.click(activity, offset=(1, 0))
            assert "PINNED" in str(detail.render())
            activity.focus()
            await pilot.press("right")
            assert snapshot["timeline"][1]["period"] in str(detail.render())

    asyncio.run(run())
