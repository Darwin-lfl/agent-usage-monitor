from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Accuracy, Agent, TokenUsage, UsageEvent, parse_timestamp
from .base import Adapter, nested, nonnegative_int, stable_id


class OpenCodeAdapter(Adapter):
    agent = Agent.OPENCODE

    @classmethod
    def default_paths(cls) -> list[Path]:
        return [
            Path("~/.local/share/opencode"),
            Path("~/.local/share/opencode/storage"),
            Path("~/Library/Application Support/opencode/storage"),
        ]

    def collect(self, since: datetime | None = None) -> list[UsageEvent]:
        paths = list(self.files(("*.json", "*.jsonl", "opencode*.db")))
        database_events = [
            event
            for path in paths
            if path.suffix == ".db"
            for event in self._sqlite_events(path)
            if since is None or event.timestamp >= since
        ]
        # OpenCode keeps legacy JSON around after SQLite migrations. Prefer the
        # current cumulative session table to avoid counting the same calls twice.
        if database_events:
            return self.finish(database_events)

        events: list[UsageEvent] = []
        for path in paths:
            if path.suffix == ".db":
                continue
            for data in self._records(path):
                event = self._parse(data, path)
                if event and (since is None or event.timestamp >= since):
                    events.append(event)
        return self.finish(events)

    def _sqlite_events(self, path: Path) -> Iterator[UsageEvent]:
        try:
            uri = f"file:{path.resolve()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                columns = {row[1] for row in connection.execute('PRAGMA table_info("session")')}
                message_events = (
                    list(self._sqlite_message_events(connection, path))
                    if "message" in tables
                    else []
                )
                if message_events:
                    yield from message_events
                    return
                required = {
                    "id",
                    "directory",
                    "time_created",
                    "tokens_input",
                    "tokens_output",
                    "tokens_reasoning",
                    "tokens_cache_read",
                    "tokens_cache_write",
                }
                if not required.issubset(columns):
                    return
                updated = "time_updated" if "time_updated" in columns else "time_created"
                cost = "cost" if "cost" in columns else "NULL"
                model = "model" if "model" in columns else "NULL"
                query = f"""SELECT id, directory, {updated}, {cost},
                    tokens_input, tokens_output, tokens_reasoning,
                    tokens_cache_read, tokens_cache_write, {model}
                    FROM session"""
                for row in connection.execute(query):
                    self.status.records_read += 1
                    timestamp = parse_timestamp(row[2])
                    if timestamp is None:
                        continue
                    model_name = _sqlite_model_name(row[9])
                    yield UsageEvent(
                        id=stable_id(self.agent.value, "session", row[0]),
                        agent=self.agent,
                        timestamp=timestamp,
                        usage=TokenUsage(
                            input=nonnegative_int(row[4]),
                            output=nonnegative_int(row[5]),
                            reasoning=nonnegative_int(row[6]),
                            cache_read=nonnegative_int(row[7]),
                            cache_write=nonnegative_int(row[8]),
                        ),
                        model=model_name,
                        session_id=str(row[0]),
                        project=str(row[1] or "unknown"),
                        cost_usd=_float_or_none(row[3]),
                        accuracy=Accuracy.EXACT,
                        source_kind="opencode_sqlite_session",
                        source_path=str(path),
                        metadata={"cumulative": True},
                    )
        except sqlite3.Error as exc:
            self.status.errors.append(f"{path}: {exc}")

    def _sqlite_message_events(
        self, connection: sqlite3.Connection, path: Path
    ) -> Iterator[UsageEvent]:
        columns = {row[1] for row in connection.execute('PRAGMA table_info("message")')}
        if not {"id", "session_id", "time_created", "data"}.issubset(columns):
            return
        updated = "m.time_updated" if "time_updated" in columns else "m.time_created"
        query = f"""SELECT m.id, m.session_id, {updated},
            json_extract(m.data, '$.tokens.input'),
            json_extract(m.data, '$.tokens.output'),
            json_extract(m.data, '$.tokens.reasoning'),
            json_extract(m.data, '$.tokens.cache.read'),
            json_extract(m.data, '$.tokens.cache.write'),
            json_extract(m.data, '$.cost'),
            json_extract(m.data, '$.providerID'),
            json_extract(m.data, '$.modelID'),
            s.directory
            FROM message m LEFT JOIN session s ON s.id = m.session_id
            WHERE json_extract(m.data, '$.tokens') IS NOT NULL"""
        for row in connection.execute(query):
            self.status.records_read += 1
            timestamp = parse_timestamp(row[2])
            if timestamp is None:
                continue
            usage = TokenUsage(
                input=nonnegative_int(row[3]),
                output=nonnegative_int(row[4]),
                reasoning=nonnegative_int(row[5]),
                cache_read=nonnegative_int(row[6]),
                cache_write=nonnegative_int(row[7]),
            )
            if usage.total <= 0:
                continue
            model_name = "/".join(str(value) for value in (row[9], row[10]) if value)
            yield UsageEvent(
                id=stable_id(self.agent.value, "message", row[0]),
                agent=self.agent,
                timestamp=timestamp,
                usage=usage,
                model=model_name or "unknown",
                session_id=str(row[1]),
                project=str(row[11] or "unknown"),
                cost_usd=_float_or_none(row[8]),
                accuracy=Accuracy.EXACT,
                source_kind="opencode_sqlite_message",
                source_path=str(path),
            )

    def _records(self, path: Path) -> Iterator[dict[str, Any]]:
        if path.suffix == ".jsonl":
            yield from self.read_jsonl(path)
            return
        try:
            value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            self.status.records_read += 1
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.status.errors.append(f"{path}: {exc}")
            return
        if isinstance(value, dict):
            yield value
        elif isinstance(value, list):
            yield from (item for item in value if isinstance(item, dict))

    def _parse(self, data: dict[str, Any], path: Path) -> UsageEvent | None:
        tokens = data.get("tokens") or data.get("usage")
        if not isinstance(tokens, dict):
            return None
        time_data = data.get("time") if isinstance(data.get("time"), dict) else {}
        timestamp = parse_timestamp(
            time_data.get("completed") or time_data.get("created") or data.get("timestamp")
        )
        if timestamp is None:
            return None
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        counts = TokenUsage(
            input=nonnegative_int(tokens.get("input") or tokens.get("input_tokens")),
            output=nonnegative_int(tokens.get("output") or tokens.get("output_tokens")),
            cache_read=nonnegative_int(cache.get("read") or tokens.get("cache_read_tokens")),
            cache_write=nonnegative_int(cache.get("write") or tokens.get("cache_write_tokens")),
            reasoning=nonnegative_int(tokens.get("reasoning")),
        )
        session_id = data.get("sessionID") or data.get("session_id") or path.parent.name
        identifier = data.get("id") or stable_id(path, timestamp.isoformat(), counts.total)
        return UsageEvent(
            id=stable_id(self.agent.value, identifier),
            agent=self.agent,
            timestamp=timestamp,
            usage=counts,
            model=str(
                data.get("modelID") or nested(data, "model", "id") or data.get("model") or "unknown"
            ),
            session_id=str(session_id),
            project=str(data.get("path") or data.get("project") or "unknown"),
            cost_usd=_float_or_none(data.get("cost")),
            accuracy=Accuracy.EXACT,
            source_kind="opencode_message_json",
            source_path=str(path),
        )


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _sqlite_model_name(value: Any) -> str:
    if not value:
        return "unknown"
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, ValueError):
        return str(value)
    if isinstance(decoded, dict):
        provider = decoded.get("providerID") or decoded.get("provider")
        model = decoded.get("id") or decoded.get("modelID") or decoded.get("model")
        return "/".join(str(part) for part in (provider, model) if part) or "unknown"
    return str(decoded)
