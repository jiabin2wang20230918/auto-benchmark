"""Iteration state machine."""

from __future__ import annotations

from enum import Enum


class IterationPhase(Enum):
    """Phases of a single optimization iteration."""

    INIT = "init"
    BASELINE = "baseline"
    CREATE_WORKTREE = "create_worktree"
    OPTIMIZE = "optimize"
    BENCHMARK = "benchmark"
    ANALYZE = "analyze"
    DECIDE = "decide"
    SAVE = "save"
    REVERT = "revert"
    CHECK_STOP = "check_stop"
    REPORT = "report"
    DONE = "done"
    ERROR = "error"


class IterationState:
    """Track the current state of the optimization loop."""

    def __init__(self) -> None:
        self.phase = IterationPhase.INIT
        self.iteration: int = 0
        self.no_improve_count: int = 0

    def set(self, phase: IterationPhase) -> None:
        self.phase = phase

    def next_iteration(self) -> int:
        self.iteration += 1
        return self.iteration

    def record_improvement(self) -> None:
        self.no_improve_count = 0

    def record_no_improvement(self) -> None:
        self.no_improve_count += 1

    @property
    def label(self) -> str:
        return f"[iter {self.iteration}] {self.phase.value}"
