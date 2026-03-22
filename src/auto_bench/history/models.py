"""History data models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MetricResult(BaseModel):
    """A single metric measurement."""

    name: str
    value: float
    direction: Literal["maximize", "minimize"]


class BenchmarkResult(BaseModel):
    """Structured benchmark result with parsed metrics."""

    metrics: list[MetricResult] = Field(default_factory=list)
    raw_output: str = ""
    exit_code: int = 0
    duration_seconds: float = 0.0

    def get_metric(self, name: str) -> float | None:
        """Get a metric value by name."""
        for m in self.metrics:
            if m.name == name:
                return m.value
        return None

    def to_dict(self) -> dict[str, float]:
        """Convert metrics to a simple name → value dict."""
        return {m.name: m.value for m in self.metrics}


class IterationRecord(BaseModel):
    """Complete record of one optimization iteration."""

    iteration_id: int
    branch_name: str
    worktree_path: str
    status: Literal["pending", "running", "optimizing", "benchmarking", "analyzing", "success", "failed", "reverted"]
    hypothesis: str = ""
    changes_summary: str = ""
    diff: str = ""
    files_changed: list[str] = Field(default_factory=list)
    baseline_metrics: dict[str, float] = Field(default_factory=dict)
    result_metrics: dict[str, float] | None = None
    improvement: dict[str, float] | None = None
    composite_score_before: float | None = None
    composite_score_after: float | None = None
    decision: Literal["keep", "revert"] | None = None
    llm_reasoning: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    error_message: str | None = None


class OptimizationReport(BaseModel):
    """Summary report of the entire optimization run."""

    project_name: str
    total_iterations: int = 0
    successful_iterations: int = 0
    reverted_iterations: int = 0
    failed_iterations: int = 0
    baseline_metrics: dict[str, float] = Field(default_factory=dict)
    final_metrics: dict[str, float] = Field(default_factory=dict)
    best_score: float = 0.0
    baseline_score: float = 0.0
    iterations: list[IterationRecord] = Field(default_factory=list)
    stop_reason: str = ""
