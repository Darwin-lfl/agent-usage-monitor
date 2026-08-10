"""Local token usage monitoring for coding agents."""

from importlib.metadata import PackageNotFoundError, version

from .models import Accuracy, Agent, TokenUsage, UsageEvent

__all__ = ["Accuracy", "Agent", "TokenUsage", "UsageEvent"]
try:
    __version__ = version("agent-usage-monitor")
except PackageNotFoundError:
    __version__ = "0.1.0"
