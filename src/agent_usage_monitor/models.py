from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Agent(str, Enum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"
    TRAE = "trae"
    QODER = "qoder"
    CODEBUDDY = "codebuddy"


class Accuracy(str, Enum):
    EXACT = "exact"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    reasoning: int = 0

    @property
    def total(self) -> int:
        # Adapters normalize overlapping counters before constructing this object.
        return self.input + self.output + self.cache_read + self.cache_write

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input=self.input + other.input,
            output=self.output + other.output,
            cache_read=self.cache_read + other.cache_read,
            cache_write=self.cache_write + other.cache_write,
            reasoning=self.reasoning + other.reasoning,
        )

    def to_dict(self) -> dict[str, int]:
        return {**asdict(self), "total": self.total}


@dataclass(slots=True)
class UsageEvent:
    id: str
    agent: Agent
    timestamp: datetime
    usage: TokenUsage
    model: str = "unknown"
    session_id: str = "unknown"
    project: str = "unknown"
    cost_usd: float | None = None
    accuracy: Accuracy = Accuracy.EXACT
    source_kind: str = "local_log"
    source_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            self.timestamp = self.timestamp.replace(tzinfo=timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent": self.agent.value,
            "timestamp": self.timestamp.isoformat(),
            "usage": self.usage.to_dict(),
            "model": self.model,
            "session_id": self.session_id,
            "project": self.project,
            "cost_usd": self.cost_usd,
            "accuracy": self.accuracy.value,
            "source": {"kind": self.source_kind, "path": self.source_path},
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class SourceStatus:
    agent: Agent
    paths: list[str]
    files_scanned: int = 0
    records_read: int = 0
    events: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.paths)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent.value,
            "available": self.available,
            "paths": self.paths,
            "files_scanned": self.files_scanned,
            "records_read": self.records_read,
            "events": self.events,
            "errors": self.errors,
        }


def parse_timestamp(value: Any, fallback: datetime | None = None) -> datetime | None:
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OSError):
            return fallback
    if not isinstance(value, str) or not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback
