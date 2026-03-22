"""Iteration history persistence using JSON files.

Uses simple JSON files instead of SQLite for zero-dependency simplicity.
Each iteration is stored as a separate JSON file for easy inspection.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from auto_bench.history.models import IterationRecord, OptimizationReport

logger = logging.getLogger(__name__)


class IterationStore:
    """Persist iteration records to disk as JSON files."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.iterations_dir = data_dir / "iterations"

    async def initialize(self) -> None:
        """Create the data directory structure."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.iterations_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Initialized data store at %s", self.data_dir)

    async def save_iteration(self, record: IterationRecord) -> None:
        """Save an iteration record to disk."""
        filename = f"iter-{record.iteration_id:03d}.json"
        path = self.iterations_dir / filename

        data = record.model_dump(mode="json")
        # Convert datetime to string
        if isinstance(data.get("timestamp"), datetime):
            data["timestamp"] = data["timestamp"].isoformat()

        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.debug("Saved iteration %d to %s", record.iteration_id, path)

    async def load_iterations(self) -> list[IterationRecord]:
        """Load all iteration records from disk."""
        records: list[IterationRecord] = []

        if not self.iterations_dir.exists():
            return records

        for path in sorted(self.iterations_dir.glob("iter-*.json")):
            try:
                with open(path) as f:
                    data = json.load(f)
                records.append(IterationRecord.model_validate(data))
            except Exception as e:
                logger.warning("Failed to load %s: %s", path, e)

        return records

    async def load_iteration(self, iteration_id: int) -> IterationRecord | None:
        """Load a specific iteration record."""
        filename = f"iter-{iteration_id:03d}.json"
        path = self.iterations_dir / filename

        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)
        return IterationRecord.model_validate(data)

    async def save_report(self, report: OptimizationReport) -> Path:
        """Save the final optimization report."""
        path = self.data_dir / "report.json"
        data = report.model_dump(mode="json")

        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

        logger.info("Saved report to %s", path)
        return path

    async def load_report(self) -> OptimizationReport | None:
        """Load the last optimization report."""
        path = self.data_dir / "report.json"
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)
        return OptimizationReport.model_validate(data)

    async def get_last_iteration_id(self) -> int:
        """Get the ID of the last saved iteration, or 0 if none."""
        records = await self.load_iterations()
        if not records:
            return 0
        return max(r.iteration_id for r in records)
