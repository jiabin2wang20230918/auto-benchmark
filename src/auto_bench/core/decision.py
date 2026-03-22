"""Decision logic for keeping or reverting iterations."""

from __future__ import annotations

from auto_bench.config.schema import MetricDefinition
from auto_bench.history.models import BenchmarkResult


def compute_composite_score(
    result: BenchmarkResult,
    definitions: list[MetricDefinition],
) -> float:
    """Compute a weighted composite score from benchmark results.

    For "maximize" metrics, the value is used directly.
    For "minimize" metrics, the negative value is used.
    All values are weighted by their definition weight.

    Returns a single scalar score where higher is always better.
    """
    score = 0.0
    total_weight = 0.0

    metrics_dict = result.to_dict()
    for defn in definitions:
        value = metrics_dict.get(defn.name)
        if value is None:
            continue

        if defn.direction == "maximize":
            score += value * defn.weight
        else:  # minimize
            score += (-value) * defn.weight

        total_weight += defn.weight

    if total_weight == 0:
        return 0.0

    return score / total_weight


def is_improved(
    baseline: BenchmarkResult,
    current: BenchmarkResult,
    definitions: list[MetricDefinition],
) -> bool:
    """Check if current results are improved over baseline.

    An iteration is considered improved if:
    1. The composite score is better, AND
    2. No individual metric degraded beyond its threshold.
    """
    baseline_dict = baseline.to_dict()
    current_dict = current.to_dict()

    any_meaningful_improvement = False

    for defn in definitions:
        base_val = baseline_dict.get(defn.name)
        curr_val = current_dict.get(defn.name)

        if base_val is None or curr_val is None:
            continue

        # Compute relative change
        if base_val == 0:
            rel_change = float("inf") if curr_val != 0 else 0.0
        else:
            rel_change = (curr_val - base_val) / abs(base_val)

        # For minimize metrics, improvement is negative change
        if defn.direction == "minimize":
            rel_change = -rel_change

        # Check for significant degradation (more than threshold in wrong direction)
        if rel_change < -defn.threshold:
            return False

        # Check for meaningful improvement
        if rel_change > defn.threshold:
            any_meaningful_improvement = True

    return any_meaningful_improvement


def compute_improvements(
    baseline: BenchmarkResult,
    current: BenchmarkResult,
    definitions: list[MetricDefinition],
) -> dict[str, float]:
    """Compute per-metric relative improvement percentages."""
    baseline_dict = baseline.to_dict()
    current_dict = current.to_dict()
    improvements: dict[str, float] = {}

    for defn in definitions:
        base_val = baseline_dict.get(defn.name)
        curr_val = current_dict.get(defn.name)

        if base_val is None or curr_val is None:
            continue

        if base_val == 0:
            improvements[defn.name] = 0.0
        else:
            rel_change = (curr_val - base_val) / abs(base_val)
            # For minimize, negative change is positive improvement
            if defn.direction == "minimize":
                rel_change = -rel_change
            improvements[defn.name] = rel_change

    return improvements
