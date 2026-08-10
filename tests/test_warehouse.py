from datetime import datetime, timezone

from agent_usage_monitor.models import Agent, TokenUsage, UsageEvent
from agent_usage_monitor.warehouse import Warehouse


def test_warehouse_is_idempotent(tmp_path):
    warehouse = Warehouse(tmp_path / "usage.sqlite3")
    event = UsageEvent(
        id="event-a",
        agent=Agent.CODEX,
        timestamp=datetime.now(timezone.utc),
        usage=TokenUsage(input=10, output=2),
    )

    warehouse.store([event, event])

    loaded = warehouse.load()
    assert len(loaded) == 1
    assert loaded[0].usage.total == 12

    updated = UsageEvent(
        id="event-a",
        agent=Agent.CODEX,
        timestamp=datetime.now(timezone.utc),
        usage=TokenUsage(input=20, output=3),
    )
    warehouse.store([updated])

    assert warehouse.load()[0].usage.total == 23
