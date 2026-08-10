from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Agent, TokenUsage, UsageEvent, parse_timestamp
from .base import Adapter, nested, nonnegative_int, stable_id


class ClaudeAdapter(Adapter):
    agent = Agent.CLAUDE

    @classmethod
    def default_paths(cls) -> list[Path]:
        return [Path("~/.claude/projects")]

    def collect(self, since: datetime | None = None) -> list[UsageEvent]:
        events: list[UsageEvent] = []
        for path in self.files(("*.jsonl",)):
            for data in self.read_jsonl(path):
                event = self._parse(data, path)
                if event and (since is None or event.timestamp >= since):
                    events.append(event)
        return self.finish(events)

    def _parse(self, data: dict[str, Any], path: Path) -> UsageEvent | None:
        usage = data.get("usage") or nested(data, "message", "usage", default={})
        if not isinstance(usage, dict):
            return None
        timestamp = parse_timestamp(data.get("timestamp"))
        if timestamp is None:
            return None
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        message_id = data.get("message_id") or message.get("id") or data.get("uuid") or ""
        request_id = data.get("requestId") or data.get("request_id") or ""
        model = data.get("model") or message.get("model") or "unknown"
        cwd = data.get("cwd") or data.get("project") or path.parent.name
        counts = TokenUsage(
            input=nonnegative_int(usage.get("input_tokens")),
            output=nonnegative_int(usage.get("output_tokens")),
            cache_read=nonnegative_int(usage.get("cache_read_input_tokens")),
            cache_write=nonnegative_int(usage.get("cache_creation_input_tokens")),
        )
        return UsageEvent(
            id=stable_id(self.agent.value, path, message_id, request_id, timestamp.isoformat()),
            agent=self.agent,
            timestamp=timestamp,
            usage=counts,
            model=str(model),
            session_id=str(data.get("sessionId") or data.get("session_id") or path.stem),
            project=str(cwd),
            cost_usd=_optional_float(data.get("costUSD") or data.get("cost_usd")),
            source_kind="claude_code_jsonl",
            source_path=str(path),
        )


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
