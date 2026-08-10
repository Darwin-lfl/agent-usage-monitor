from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .models import Accuracy, Agent, TokenUsage, UsageEvent, parse_timestamp


class Warehouse:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()

    def store(self, events: list[UsageEvent]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS usage_events (
                id TEXT PRIMARY KEY, agent TEXT NOT NULL, timestamp TEXT NOT NULL,
                input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL,
                cache_read_tokens INTEGER NOT NULL, cache_write_tokens INTEGER NOT NULL,
                reasoning_tokens INTEGER NOT NULL, model TEXT, session_id TEXT, project TEXT,
                cost_usd REAL, accuracy TEXT NOT NULL, source_kind TEXT, source_path TEXT,
                metadata TEXT NOT NULL)"""
            )
            connection.executemany(
                """INSERT OR REPLACE INTO usage_events VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        event.id,
                        event.agent.value,
                        event.timestamp.isoformat(),
                        event.usage.input,
                        event.usage.output,
                        event.usage.cache_read,
                        event.usage.cache_write,
                        event.usage.reasoning,
                        event.model,
                        event.session_id,
                        event.project,
                        event.cost_usd,
                        event.accuracy.value,
                        event.source_kind,
                        event.source_path,
                        json.dumps(event.metadata),
                    )
                    for event in events
                ],
            )
            connection.commit()

    def load(self, since: datetime | None = None) -> list[UsageEvent]:
        if not self.path.exists():
            return []
        query = "SELECT * FROM usage_events"
        parameters: tuple[str, ...] = ()
        if since:
            query += " WHERE timestamp >= ?"
            parameters = (since.isoformat(),)
        with closing(sqlite3.connect(self.path)) as connection:
            rows = connection.execute(query, parameters).fetchall()
        events = []
        for row in rows:
            timestamp = parse_timestamp(row[2])
            if timestamp is None:
                continue
            events.append(
                UsageEvent(
                    id=row[0],
                    agent=Agent(row[1]),
                    timestamp=timestamp,
                    usage=TokenUsage(row[3], row[4], row[5], row[6], row[7]),
                    model=row[8],
                    session_id=row[9],
                    project=row[10],
                    cost_usd=row[11],
                    accuracy=Accuracy(row[12]),
                    source_kind=row[13],
                    source_path=row[14],
                    metadata=json.loads(row[15]),
                )
            )
        return events
