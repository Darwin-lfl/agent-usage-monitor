from __future__ import annotations

from pathlib import Path

from ..models import Agent
from .base import Adapter
from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .ide import CodeBuddyAdapter, QoderAdapter, TraeAdapter
from .opencode import OpenCodeAdapter

ADAPTERS: dict[Agent, type[Adapter]] = {
    Agent.CLAUDE: ClaudeAdapter,
    Agent.CODEX: CodexAdapter,
    Agent.OPENCODE: OpenCodeAdapter,
    Agent.TRAE: TraeAdapter,
    Agent.QODER: QoderAdapter,
    Agent.CODEBUDDY: CodeBuddyAdapter,
}


def build_adapters(
    agents: list[Agent] | None = None,
    custom_paths: dict[Agent, list[Path]] | None = None,
    include_estimates: bool = True,
) -> list[Adapter]:
    selected = agents or list(Agent)
    result: list[Adapter] = []
    for agent in selected:
        cls = ADAPTERS[agent]
        paths = (custom_paths or {}).get(agent)
        if issubclass(cls, (TraeAdapter, QoderAdapter, CodeBuddyAdapter)):
            result.append(cls(paths=paths, include_estimates=include_estimates))
        else:
            result.append(cls(paths=paths))
    return result
