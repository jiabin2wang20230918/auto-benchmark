"""AnalyzerAgent: evaluates benchmark results and decides keep/revert."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from agents import Agent, ModelSettings, RunConfig, Runner

from auto_bench.agent.context import AgentContext
from auto_bench.agent.model_provider import AutoBenchModelProvider, AnthropicModelProvider, create_model_provider
from auto_bench.config.schema import AutoBenchConfig, LLMConfig
from auto_bench.history.models import BenchmarkResult

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "analyzer.md"


@dataclass
class AnalysisResult:
    """Result of a benchmark analysis."""

    decision: str  # "keep" or "revert"
    reasoning: str
    metric_analysis: dict
    suggestions: str
    raw_output: str


class AnalyzerAgent:
    """Agent that analyzes benchmark results and recommends keep/revert."""

    def __init__(
        self,
        config: LLMConfig,
        model_provider: AutoBenchModelProvider | AnthropicModelProvider | None = None,
    ) -> None:
        self.config = config
        self._model_provider = model_provider or create_model_provider(config)

    def _build_agent(self, system_prompt: str) -> Agent[AgentContext]:
        """Create the Agent instance (no tools needed for analysis)."""
        return Agent[AgentContext](
            name="AnalyzerAgent",
            instructions=system_prompt,
            tools=[],  # Analyzer only reasons, no tools needed
            model=self.config.model,
            model_settings=ModelSettings(
                temperature=0.3,  # Lower temperature for more deterministic analysis
                max_tokens=self.config.max_tokens,
            ),
        )

    def _build_system_prompt(
        self,
        config: AutoBenchConfig,
        baseline: BenchmarkResult,
        current: BenchmarkResult,
        diff: str,
        hypothesis: str,
    ) -> str:
        """Build the analysis prompt with all context."""
        template = PROMPT_PATH.read_text()

        # Build metrics description
        metrics_desc_parts = []
        for defn in config.metrics.definitions:
            metrics_desc_parts.append(
                f"- {defn.name}: {defn.direction} (threshold: {defn.threshold}, weight: {defn.weight})"
            )
        metrics_desc = "\n".join(metrics_desc_parts)

        baseline_str = "\n".join(f"- {k}: {v}" for k, v in baseline.to_dict().items())
        current_str = "\n".join(f"- {k}: {v}" for k, v in current.to_dict().items())

        # Truncate diff if too long
        max_diff = 10_000
        if len(diff) > max_diff:
            diff = diff[:max_diff] + "\n... (diff truncated)"

        return template.format(
            metrics_description=metrics_desc,
            baseline_metrics=baseline_str,
            current_metrics=current_str,
            diff=diff,
            hypothesis=hypothesis,
        )

    async def analyze_results(
        self,
        config: AutoBenchConfig,
        baseline: BenchmarkResult,
        current: BenchmarkResult,
        diff: str,
        hypothesis: str,
        worktree_path: Path,
        iteration_id: int,
    ) -> AnalysisResult:
        """Analyze benchmark results and return a keep/revert decision."""
        system_prompt = self._build_system_prompt(
            config, baseline, current, diff, hypothesis
        )
        agent = self._build_agent(system_prompt)

        context = AgentContext(
            config=config,
            worktree_path=worktree_path,
            iteration_id=iteration_id,
            baseline_metrics=baseline.to_dict(),
        )

        user_msg = (
            "Analyze the benchmark results above. "
            "Compare the baseline and current metrics, then decide whether to keep or revert the changes. "
            "Respond with the JSON format specified in your instructions."
        )

        logger.info("Running AnalyzerAgent for iteration %d...", iteration_id)

        result = await Runner.run(
            agent,
            input=user_msg,
            context=context,
            max_turns=3,
            run_config=RunConfig(
                model_provider=self._model_provider,
            ),
        )

        output_text = result.final_output or ""
        return self._parse_result(output_text)

    def _parse_result(self, text: str) -> AnalysisResult:
        """Parse the agent's JSON output into an AnalysisResult."""
        # Try to extract JSON from the response
        json_data = self._extract_json(text)

        if json_data:
            return AnalysisResult(
                decision=json_data.get("decision", "revert"),
                reasoning=json_data.get("reasoning", ""),
                metric_analysis=json_data.get("metric_analysis", {}),
                suggestions=json_data.get("suggestions", ""),
                raw_output=text,
            )

        # Fallback: try to detect decision from text
        lower = text.lower()
        decision = "keep" if "keep" in lower and "revert" not in lower else "revert"

        return AnalysisResult(
            decision=decision,
            reasoning=text,
            metric_analysis={},
            suggestions="",
            raw_output=text,
        )

    @staticmethod
    def _extract_json(text: str) -> dict | None:
        """Extract a JSON object from text that may contain markdown code blocks."""
        # Try to find JSON in ```json ... ``` blocks
        json_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if json_block:
            try:
                return json.loads(json_block.group(1))
            except json.JSONDecodeError:
                pass

        # Try to parse the entire text as JSON
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try to find first { ... } block
        start = text.find("{")
        if start != -1:
            for end in range(len(text) - 1, start, -1):
                if text[end] == "}":
                    try:
                        return json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        continue

        return None
