from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models import Agent, SourceStatus, UsageEvent

MAX_LOG_BYTES = 64 * 1024 * 1024
QUERYABLE_DATABASE_SUFFIXES = {".db", ".sqlite", ".vscdb"}


class Adapter(ABC):
    agent: Agent

    def __init__(self, paths: Iterable[Path] | None = None) -> None:
        candidates = list(paths) if paths is not None else self.default_paths()
        self.paths = _dedupe_paths(p.expanduser() for p in candidates)
        self.status = SourceStatus(
            agent=self.agent, paths=[str(path) for path in self.paths if path.exists()]
        )

    @classmethod
    @abstractmethod
    def default_paths(cls) -> list[Path]: ...

    @abstractmethod
    def collect(self, since: datetime | None = None) -> list[UsageEvent]: ...

    def files(self, patterns: tuple[str, ...]) -> Iterator[Path]:
        seen: set[Path] = set()
        for root in self.paths:
            if root.is_file():
                candidates = [root]
            elif root.is_dir():
                candidates = [file for pattern in patterns for file in root.rglob(pattern)]
            else:
                continue
            for file in candidates:
                try:
                    resolved = file.resolve()
                    too_large_to_read_whole = (
                        file.suffix.lower() not in QUERYABLE_DATABASE_SUFFIXES
                        and file.stat().st_size > MAX_LOG_BYTES
                    )
                    if resolved in seen or not file.is_file() or too_large_to_read_whole:
                        continue
                except OSError:
                    continue
                seen.add(resolved)
                self.status.files_scanned += 1
                yield file

    def read_jsonl(self, path: Path) -> Iterator[dict[str, Any]]:
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        value = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if isinstance(value, dict):
                        self.status.records_read += 1
                        yield value
        except OSError as exc:
            self.status.errors.append(f"{path}: {exc}")

    def finish(self, events: list[UsageEvent]) -> list[UsageEvent]:
        unique: dict[str, UsageEvent] = {}
        for event in events:
            if event.usage.total <= 0:
                continue
            existing = unique.get(event.id)
            if existing is None or event.timestamp >= existing.timestamp:
                unique[event.id] = event
        result = sorted(unique.values(), key=lambda event: event.timestamp)
        self.status.events = len(result)
        return result


def stable_id(*parts: object) -> str:
    raw = "\0".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]


def nested(data: dict[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key not in seen:
            result.append(path)
            seen.add(key)
    return result
