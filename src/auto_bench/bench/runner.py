"""Benchmark execution engine."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from auto_bench.config.schema import BenchmarkConfig

logger = logging.getLogger(__name__)


@dataclass
class RawBenchmarkOutput:
    """Raw output from a benchmark run."""

    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float


class BenchmarkRunner:
    """Execute benchmark commands in a target directory."""

    def __init__(self, config: BenchmarkConfig) -> None:
        self.config = config

    async def run(self, working_root: Path) -> RawBenchmarkOutput:
        """Run the benchmark in the given directory.

        Args:
            working_root: Root directory (typically a worktree path).

        Returns:
            RawBenchmarkOutput with stdout, stderr, exit code, and duration.

        Raises:
            TimeoutError: If the benchmark exceeds the configured timeout.
        """
        cwd = working_root / self.config.working_dir

        # Optional setup step
        if self.config.setup_command:
            logger.info("Running setup command: %s", self.config.setup_command)
            await self._exec(self.config.setup_command, cwd, timeout=self.config.timeout)

        # Run the benchmark
        logger.info("Running benchmark: %s (cwd=%s)", self.config.command, cwd)
        return await self._exec(self.config.command, cwd, timeout=self.config.timeout)

    async def _exec(self, command: str, cwd: Path, timeout: int) -> RawBenchmarkOutput:
        """Execute a shell command with timeout."""
        start = time.monotonic()

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            duration = time.monotonic() - start
            raise TimeoutError(
                f"Benchmark timed out after {duration:.1f}s (limit: {timeout}s): {command}"
            )

        duration = time.monotonic() - start
        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        logger.info(
            "Benchmark finished: exit_code=%d, duration=%.1fs",
            proc.returncode or 0,
            duration,
        )

        return RawBenchmarkOutput(
            stdout=stdout,
            stderr=stderr,
            exit_code=proc.returncode or 0,
            duration_seconds=duration,
        )
