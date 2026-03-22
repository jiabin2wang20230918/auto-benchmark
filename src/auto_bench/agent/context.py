"""Agent context shared across all tools during an optimization iteration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from auto_bench.config.schema import AutoBenchConfig


@dataclass
class AgentContext:
    """Shared context passed to all agent tools via RunContextWrapper."""

    config: AutoBenchConfig
    worktree_path: Path
    iteration_id: int
    baseline_metrics: dict[str, float] = field(default_factory=dict)
    history_summary: str = ""
