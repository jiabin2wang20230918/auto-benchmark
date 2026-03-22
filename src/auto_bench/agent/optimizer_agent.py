"""OptimizerAgent: uses LLM to analyze code and apply modifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from agents import Agent, ModelSettings, RunConfig, Runner

from auto_bench.agent.context import AgentContext
from auto_bench.agent.model_provider import AutoBenchModelProvider, AnthropicModelProvider, create_model_provider
from auto_bench.agent.tools.bash_exec import bash_exec
from auto_bench.agent.tools.bench_run import bench_run
from auto_bench.agent.tools.code_edit import code_edit, code_write
from auto_bench.agent.tools.code_read import code_read, list_files
from auto_bench.agent.tools.code_search import code_search
from auto_bench.agent.tools.git_ops import git_diff, git_log
from auto_bench.config.schema import AutoBenchConfig, LLMConfig

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "optimizer.md"


@dataclass
class ProposalResult:
    """Result of an optimization proposal."""

    hypothesis: str
    changes_summary: str
    files_modified: list[str]
    raw_output: str


class OptimizerAgent:
    """Agent that analyzes code and applies optimizations."""

    def __init__(
        self,
        config: LLMConfig,
        model_provider: AutoBenchModelProvider | AnthropicModelProvider | None = None,
    ) -> None:
        self.config = config
        self._model_provider = model_provider or create_model_provider(config)

    def _build_agent(self, system_prompt: str) -> Agent[AgentContext]:
        """Create the Agent instance with tools."""
        return Agent[AgentContext](
            name="OptimizerAgent",
            instructions=system_prompt,
            tools=[
                code_read,
                list_files,
                code_edit,
                code_write,
                code_search,
                bash_exec,
                git_diff,
                git_log,
            ],
            model=self.config.model,
            model_settings=ModelSettings(
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            ),
        )

    def _build_system_prompt(
        self,
        bench_config: AutoBenchConfig,
        baseline_metrics: dict[str, float],
        history_summary: str,
    ) -> str:
        """Build the system prompt with context."""
        template = PROMPT_PATH.read_text()

        # Build metrics description
        metrics_desc_parts = []
        for defn in bench_config.metrics.definitions:
            metrics_desc_parts.append(
                f"- {defn.name}: {defn.direction} (threshold: {defn.threshold}, weight: {defn.weight})"
            )
        metrics_desc = "\n".join(metrics_desc_parts) or "No specific metrics defined."

        # Format baseline
        baseline_str = "\n".join(f"- {k}: {v}" for k, v in baseline_metrics.items()) or "No baseline data."

        # Exclude files
        exclude_str = "\n".join(
            f"- {p}" for p in bench_config.optimization.exclude_files
        ) or "None"

        return template.format(
            metrics_description=metrics_desc,
            baseline_metrics=baseline_str,
            history_summary=history_summary or "This is the first iteration.",
            exclude_files=exclude_str,
        )

    async def propose_and_apply(
        self,
        worktree_path: Path,
        config: AutoBenchConfig,
        baseline_metrics: dict[str, float],
        iteration_id: int,
        history_summary: str = "",
    ) -> ProposalResult:
        """Have the agent analyze the code and make modifications.

        The agent will use its tools to read, search, and edit code directly
        in the worktree.

        Returns:
            ProposalResult with hypothesis, summary, and list of modified files.
        """
        system_prompt = self._build_system_prompt(config, baseline_metrics, history_summary)
        agent = self._build_agent(system_prompt)

        context = AgentContext(
            config=config,
            worktree_path=worktree_path,
            iteration_id=iteration_id,
            baseline_metrics=baseline_metrics,
            history_summary=history_summary,
        )

        user_msg = (
            f"This is optimization iteration #{iteration_id}. "
            f"Analyze the project code and make a targeted modification to improve the benchmark metrics. "
            f"Start by listing the project files and reading the key source files."
        )

        logger.info("Running OptimizerAgent for iteration %d...", iteration_id)

        result = await Runner.run(
            agent,
            input=user_msg,
            context=context,
            max_turns=30,
            run_config=RunConfig(
                model_provider=self._model_provider,
            ),
        )

        output_text = result.final_output or ""
        return self._parse_result(output_text)

    def _parse_result(self, text: str) -> ProposalResult:
        """Parse the agent's output into a ProposalResult."""
        hypothesis = ""
        changes_summary = ""
        files_modified: list[str] = []

        for line in text.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("HYPOTHESIS:"):
                hypothesis = line_stripped[len("HYPOTHESIS:"):].strip()
            elif line_stripped.startswith("CHANGES:"):
                changes_summary = line_stripped[len("CHANGES:"):].strip()
            elif line_stripped.startswith("FILES_MODIFIED:"):
                raw = line_stripped[len("FILES_MODIFIED:"):].strip()
                files_modified = [f.strip() for f in raw.split(",") if f.strip()]

        # Fallback if structured output not found
        if not hypothesis:
            hypothesis = text[:200] if text else "No hypothesis provided."
        if not changes_summary:
            changes_summary = hypothesis

        return ProposalResult(
            hypothesis=hypothesis,
            changes_summary=changes_summary,
            files_modified=files_modified,
            raw_output=text,
        )
