from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Accuracy, Agent, TokenUsage, UsageEvent, parse_timestamp
from .base import Adapter, nonnegative_int, stable_id

TOKEN_KEYS = {
    "input": ("input", "input_tokens", "inputTokens", "prompt_tokens", "promptTokens"),
    "output": ("output", "output_tokens", "outputTokens", "completion_tokens", "completionTokens"),
    "cache_read": ("cache_read", "cache_read_tokens", "cacheReadTokens", "cached_input_tokens"),
    "cache_write": ("cache_write", "cache_write_tokens", "cacheWriteTokens"),
    "reasoning": ("reasoning", "reasoning_tokens", "reasoningTokens"),
}


class IDEStorageAdapter(Adapter):
    product_names: tuple[str, ...] = ()

    @classmethod
    def default_paths(cls) -> list[Path]:
        roots: list[Path] = []
        for product in cls.product_names:
            if sys.platform == "darwin":
                roots.append(Path(f"~/Library/Application Support/{product}/User"))
            elif sys.platform == "win32":
                roots.append(Path(f"~/AppData/Roaming/{product}/User"))
            else:
                roots.append(Path(f"~/.config/{product}/User"))
        return roots

    def __init__(self, paths=None, include_estimates: bool = True) -> None:
        super().__init__(paths)
        self.include_estimates = include_estimates

    def collect(self, since: datetime | None = None) -> list[UsageEvent]:
        events: list[UsageEvent] = []
        for path in self.files(("*.json", "*.jsonl", "*.vscdb", "*.sqlite", "*.db")):
            for record in self._records(path):
                events.extend(self._extract(record, path, since))
        return self.finish(events)

    def _records(self, path: Path) -> Iterator[dict[str, Any]]:
        if path.suffix == ".jsonl":
            yield from self.read_jsonl(path)
        elif path.suffix == ".json":
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                self.status.records_read += 1
                yield from _dict_records(data)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                self.status.errors.append(f"{path}: {exc}")
        else:
            yield from self._sqlite_records(path)

    def _sqlite_records(self, path: Path) -> Iterator[dict[str, Any]]:
        try:
            uri = f"file:{path.resolve()}?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as connection:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
                for (table,) in tables:
                    safe_table = table.replace('"', '""')
                    columns = connection.execute(f'PRAGMA table_info("{safe_table}")').fetchall()
                    text_columns = [
                        row[1] for row in columns if str(row[2]).upper() in {"", "TEXT"}
                    ]
                    for column in text_columns:
                        safe_column = column.replace('"', '""')
                        query = f'SELECT "{safe_column}" FROM "{safe_table}" LIMIT 5000'
                        for (value,) in connection.execute(query).fetchmany(5000):
                            if not isinstance(value, str) or len(value) > 8_000_000:
                                continue
                            try:
                                decoded = json.loads(value)
                            except (json.JSONDecodeError, ValueError):
                                continue
                            self.status.records_read += 1
                            yield from _dict_records(decoded)
        except sqlite3.Error as exc:
            self.status.errors.append(f"{path}: {exc}")

    def _extract(
        self, record: dict[str, Any], path: Path, since: datetime | None
    ) -> list[UsageEvent]:
        result: list[UsageEvent] = []
        for item in _walk_dicts(record):
            timestamp = _find_timestamp(item, path)
            if timestamp is None or (since is not None and timestamp < since):
                continue
            usage = _usage_from_dict(item)
            accuracy = Accuracy.EXACT
            if usage.total == 0 and self.include_estimates:
                usage = _estimated_message_usage(item)
                accuracy = Accuracy.ESTIMATED
            if usage.total == 0:
                continue
            identifier = item.get("id") or item.get("messageId") or item.get("requestId")
            result.append(
                UsageEvent(
                    id=stable_id(
                        self.agent.value,
                        path,
                        identifier or timestamp.isoformat(),
                        usage.total,
                        item.get("role", ""),
                    ),
                    agent=self.agent,
                    timestamp=timestamp,
                    usage=usage,
                    model=str(item.get("model") or item.get("modelId") or "unknown"),
                    session_id=str(
                        item.get("sessionId") or item.get("conversationId") or path.parent.name
                    ),
                    project=str(item.get("workspace") or item.get("cwd") or "unknown"),
                    accuracy=accuracy,
                    source_kind=(
                        "ide_storage_exact" if accuracy is Accuracy.EXACT else "text_estimate"
                    ),
                    source_path=str(path),
                )
            )
        return result


class TraeAdapter(IDEStorageAdapter):
    agent = Agent.TRAE
    product_names = ("Trae", "trae")


class QoderAdapter(IDEStorageAdapter):
    agent = Agent.QODER
    product_names = ("Qoder", "qoder")


class CodeBuddyAdapter(IDEStorageAdapter):
    agent = Agent.CODEBUDDY
    product_names = ("CodeBuddy", "codebuddy")


def _dict_records(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        yield from (item for item in value if isinstance(item, dict))


def _walk_dicts(value: Any, depth: int = 0) -> Iterator[dict[str, Any]]:
    if depth > 12:
        return
    if isinstance(value, dict):
        yield value
        for key, child in value.items():
            if key in {"usage", "tokens", "tokenUsage", "token_usage"}:
                continue
            yield from _walk_dicts(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child, depth + 1)


def _value(data: dict[str, Any], names: tuple[str, ...]) -> int:
    for name in names:
        if name in data:
            return nonnegative_int(data[name])
    return 0


def _usage_from_dict(data: dict[str, Any]) -> TokenUsage:
    candidates = [data]
    candidates.extend(
        value
        for key, value in data.items()
        if key in {"usage", "tokens", "tokenUsage", "token_usage"} and isinstance(value, dict)
    )
    for candidate in reversed(candidates):
        usage = TokenUsage(**{name: _value(candidate, keys) for name, keys in TOKEN_KEYS.items()})
        if usage.total:
            return usage
    return TokenUsage()


def _find_timestamp(data: dict[str, Any], path: Path) -> datetime | None:
    for key in ("timestamp", "createdAt", "created_at", "completedAt", "updatedAt", "time"):
        timestamp = parse_timestamp(data.get(key))
        if timestamp:
            return timestamp
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def _estimated_message_usage(data: dict[str, Any]) -> TokenUsage:
    role = str(data.get("role") or data.get("type") or "").lower()
    if role not in {"user", "human", "assistant", "ai"}:
        return TokenUsage()
    content = data.get("content") or data.get("text") or data.get("message")
    if isinstance(content, list):
        content = " ".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part) for part in content
        )
    if not isinstance(content, str) or not content.strip():
        return TokenUsage()
    ascii_chars = sum(ord(char) < 128 for char in content)
    estimated = max(1, math.ceil(ascii_chars / 4 + (len(content) - ascii_chars) / 1.5))
    if role in {"assistant", "ai"}:
        return TokenUsage(output=estimated)
    return TokenUsage(input=estimated)
