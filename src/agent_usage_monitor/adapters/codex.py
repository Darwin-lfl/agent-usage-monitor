from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..models import Agent, TokenUsage, UsageEvent, parse_timestamp
from .base import Adapter, nested, nonnegative_int, stable_id


class CodexAdapter(Adapter):
    agent = Agent.CODEX

    @classmethod
    def default_paths(cls) -> list[Path]:
        return [Path("~/.codex/sessions"), Path("~/.codex/archived_sessions")]

    def collect(self, since: datetime | None = None) -> list[UsageEvent]:
        events: list[UsageEvent] = []
        for path in self.files(("*.jsonl",)):
            events.extend(self._collect_file(path, since))
        return self.finish(events)

    def _collect_file(self, path: Path, since: datetime | None) -> list[UsageEvent]:
        events: list[UsageEvent] = []
        unresolved_models: list[UsageEvent] = []
        previous = TokenUsage()
        session_id, project, model = path.stem, "unknown", "unknown"
        for index, data in enumerate(self.read_jsonl(path)):
            payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
            record_type = data.get("type")
            if record_type == "session_meta":
                session_id = str(payload.get("id") or session_id)
                project = str(payload.get("cwd") or project)
            model_candidate = _model_from_record(record_type, payload)
            if model_candidate:
                model = model_candidate
                for event in unresolved_models:
                    event.model = model
                unresolved_models.clear()
            if record_type == "session_meta":
                continue
            if record_type != "event_msg" or payload.get("type") != "token_count":
                continue
            total = nested(payload, "info", "total_token_usage", default={})
            if not isinstance(total, dict):
                continue
            timestamp = parse_timestamp(data.get("timestamp"))
            if timestamp is None:
                continue
            cached = nonnegative_int(total.get("cached_input_tokens"))
            current = TokenUsage(
                input=max(0, nonnegative_int(total.get("input_tokens")) - cached),
                output=nonnegative_int(total.get("output_tokens")),
                cache_read=cached,
                reasoning=nonnegative_int(total.get("reasoning_output_tokens")),
            )
            delta = _monotonic_delta(previous, current)
            previous = current
            if delta.total == 0 or (since is not None and timestamp < since):
                continue
            event = UsageEvent(
                id=stable_id(self.agent.value, path, index, current.total),
                agent=self.agent,
                timestamp=timestamp,
                usage=delta,
                model=model,
                session_id=session_id,
                project=project,
                source_kind="codex_rollout_jsonl",
                source_path=str(path),
                metadata={
                    "cumulative_total": current.total,
                    "model_context_window": nested(payload, "info", "model_context_window"),
                },
            )
            events.append(event)
            if model == "unknown":
                unresolved_models.append(event)
        return events


def _model_from_record(record_type: object, payload: dict) -> str | None:
    if record_type in {"session_meta", "turn_context"}:
        value = payload.get("model")
    elif record_type == "event_msg" and payload.get("type") == "thread_settings_applied":
        value = nested(payload, "thread_settings", "model")
    else:
        return None
    return value if isinstance(value, str) and value else None


def _monotonic_delta(previous: TokenUsage, current: TokenUsage) -> TokenUsage:
    if current.total < previous.total:
        return current
    return TokenUsage(
        input=max(0, current.input - previous.input),
        output=max(0, current.output - previous.output),
        cache_read=max(0, current.cache_read - previous.cache_read),
        cache_write=max(0, current.cache_write - previous.cache_write),
        reasoning=max(0, current.reasoning - previous.reasoning),
    )
