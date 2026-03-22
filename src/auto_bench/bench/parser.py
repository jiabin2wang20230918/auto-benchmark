"""Benchmark result parsing: extract structured metrics from raw output."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from jsonpath_ng import parse as jsonpath_parse

from auto_bench.config.schema import MetricDefinition, MetricsConfig
from auto_bench.history.models import BenchmarkResult, MetricResult

from .runner import RawBenchmarkOutput

logger = logging.getLogger(__name__)


class ResultParser:
    """Parse benchmark output into structured metric results."""

    def __init__(self, config: MetricsConfig) -> None:
        self.config = config

    def parse(self, output: RawBenchmarkOutput, working_root: Path | None = None) -> BenchmarkResult:
        """Parse raw benchmark output into BenchmarkResult.

        Args:
            output: Raw benchmark output.
            working_root: Project root (for reading result files).

        Returns:
            BenchmarkResult with extracted metrics.
        """
        if output.exit_code != 0:
            logger.warning("Benchmark exited with code %d", output.exit_code)

        if self.config.source == "json":
            metrics = self._parse_json(output, working_root)
        elif self.config.source == "regex":
            metrics = self._parse_regex(output)
        elif self.config.source == "stdout_kv":
            metrics = self._parse_kv(output)
        else:
            raise ValueError(f"Unknown metrics source: {self.config.source}")

        return BenchmarkResult(
            metrics=metrics,
            raw_output=output.stdout,
            exit_code=output.exit_code,
            duration_seconds=output.duration_seconds,
        )

    def _parse_json(
        self, output: RawBenchmarkOutput, working_root: Path | None
    ) -> list[MetricResult]:
        """Parse JSON output (from stdout or a file)."""
        # Load JSON data
        if self.config.json_file and working_root:
            json_path = working_root / self.config.json_file
            with open(json_path) as f:
                data = json.load(f)
        else:
            # Parse JSON from stdout — find the first valid JSON object
            data = self._extract_json_from_stdout(output.stdout)

        if data is None:
            logger.error("Could not parse JSON from benchmark output")
            return []

        # Extract metrics using JSONPath
        metrics: list[MetricResult] = []
        for defn in self.config.definitions:
            value = self._extract_jsonpath(data, defn)
            if value is not None:
                metrics.append(MetricResult(
                    name=defn.name,
                    value=value,
                    direction=defn.direction,
                ))
            else:
                logger.warning("Metric %s not found in JSON output", defn.name)

        return metrics

    def _parse_regex(self, output: RawBenchmarkOutput) -> list[MetricResult]:
        """Parse metrics from stdout using regex patterns."""
        metrics: list[MetricResult] = []
        text = output.stdout

        for defn in self.config.definitions:
            if not defn.regex:
                logger.warning("Metric %s has no regex pattern", defn.name)
                continue

            match = re.search(defn.regex, text)
            if match:
                try:
                    # Try named group 'value' first, then group 1
                    raw = match.group("value") if "value" in match.groupdict() else match.group(1)
                    value = float(raw)
                    metrics.append(MetricResult(
                        name=defn.name,
                        value=value,
                        direction=defn.direction,
                    ))
                except (IndexError, ValueError) as e:
                    logger.warning("Could not extract value for metric %s: %s", defn.name, e)
            else:
                logger.warning("Regex did not match for metric %s", defn.name)

        return metrics

    def _parse_kv(self, output: RawBenchmarkOutput) -> list[MetricResult]:
        """Parse key=value or key: value pairs from stdout."""
        metrics: list[MetricResult] = []
        text = output.stdout

        # Build a lookup from stdout lines
        kv_map: dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            # Match "key: value" or "key = value" or "key=value"
            m = re.match(r"^([\w@_.-]+)\s*[:=]\s*(.+)$", line)
            if m:
                kv_map[m.group(1).strip()] = m.group(2).strip()

        for defn in self.config.definitions:
            raw = kv_map.get(defn.name)
            if raw is not None:
                try:
                    value = float(raw)
                    metrics.append(MetricResult(
                        name=defn.name,
                        value=value,
                        direction=defn.direction,
                    ))
                except ValueError:
                    logger.warning("Could not convert value for %s: %s", defn.name, raw)
            else:
                logger.warning("Metric %s not found in stdout key-value pairs", defn.name)

        return metrics

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_from_stdout(text: str) -> dict | list | None:
        """Try to find and parse a JSON object/array from stdout text."""
        # Strategy 1: entire stdout is valid JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Strategy 2: find the first { ... } or [ ... ] block
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = text.find(start_char)
            if start == -1:
                continue
            # Find matching end by trying progressively larger substrings
            for end in range(len(text) - 1, start, -1):
                if text[end] == end_char:
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        continue

        return None

    @staticmethod
    def _extract_jsonpath(data: dict | list, defn: MetricDefinition) -> float | None:
        """Extract a numeric value using JSONPath expression."""
        if not defn.json_key:
            return None

        try:
            expr = jsonpath_parse(defn.json_key)
            matches = expr.find(data)
            if matches:
                return float(matches[0].value)
        except Exception as e:
            logger.warning("JSONPath extraction failed for %s: %s", defn.name, e)

        return None
