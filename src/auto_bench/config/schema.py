"""Configuration schema definitions using Pydantic v2."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ProjectConfig(BaseModel):
    """Target project configuration."""

    name: str = Field(description="Human-readable project name")
    path: Path = Field(description="Absolute path to the target project (must be a git repo)")
    base_branch: str = Field(default="main", description="Branch to base optimizations on")


class BenchmarkConfig(BaseModel):
    """Benchmark execution configuration."""

    command: str = Field(description="Shell command to run the benchmark")
    working_dir: str = Field(default=".", description="Working directory relative to project root")
    timeout: int = Field(default=300, description="Benchmark timeout in seconds")
    setup_command: str | None = Field(default=None, description="Optional setup command before benchmark")


class MetricDefinition(BaseModel):
    """Single metric extraction and evaluation rule."""

    name: str = Field(description="Metric identifier")
    json_key: str | None = Field(default=None, description="JSONPath expression for JSON source")
    regex: str | None = Field(default=None, description="Regex pattern with named group 'value' for regex source")
    direction: Literal["maximize", "minimize"] = Field(description="Optimization direction")
    threshold: float = Field(default=0.01, description="Minimum relative improvement to be considered meaningful")
    weight: float = Field(default=1.0, description="Weight for multi-metric composite scoring")


class MetricsConfig(BaseModel):
    """Metrics extraction configuration."""

    source: Literal["json", "regex", "stdout_kv"] = Field(
        default="json", description="How to parse benchmark output"
    )
    json_file: str | None = Field(
        default=None, description="Path to JSON results file (null = parse stdout)"
    )
    definitions: list[MetricDefinition] = Field(description="Metrics to track")


class OptimizationConfig(BaseModel):
    """Optimization loop parameters."""

    max_iterations: int = Field(default=20, description="Maximum number of optimization iterations")
    max_no_improve: int = Field(default=5, description="Stop after N consecutive iterations without improvement")
    strategy: Literal["single_change", "batch_change"] = Field(
        default="single_change",
        description="single_change: one focused change per iteration; batch_change: multiple changes",
    )
    focus_files: list[str] = Field(default_factory=list, description="Glob patterns to limit scope of modifications")
    exclude_files: list[str] = Field(
        default_factory=lambda: ["tests/**", "benchmark/**"],
        description="Glob patterns to exclude from modifications",
    )


class AgentLLMOverride(BaseModel):
    """Per-agent LLM overrides. All fields are optional; unset fields fall back to the global LLMConfig."""

    provider: Literal["openai", "anthropic"] | None = Field(
        default=None, description="LLM provider override ('openai' or 'anthropic')"
    )
    model: str | None = Field(default=None, description="Model name override")
    api_base: str | None = Field(default=None, description="Custom API base URL override")
    api_key: str | None = Field(default=None, description="API key override")
    temperature: float | None = Field(default=None, description="Sampling temperature override")
    max_tokens: int | None = Field(default=None, description="Max output tokens override")


class LLMConfig(BaseModel):
    """LLM provider configuration."""

    provider: Literal["openai", "anthropic"] = Field(
        default="openai",
        description="LLM provider ('openai' for OpenAI-compatible APIs, 'anthropic' for Anthropic API)",
    )
    model: str = Field(default="gpt-4o", description="Model name")
    api_base: str | None = Field(default=None, description="Custom API base URL")
    api_key: str | None = Field(default=None, description="API key (overrides env var)")
    temperature: float = Field(default=0.7, description="Sampling temperature for optimizer agent")
    max_tokens: int = Field(default=16000, description="Max output tokens")

    optimizer: AgentLLMOverride | None = Field(default=None, description="Optional LLM overrides for OptimizerAgent")
    analyzer: AgentLLMOverride | None = Field(default=None, description="Optional LLM overrides for AnalyzerAgent")

    def resolve_for(self, agent: str) -> "LLMConfig":
        """Return a resolved LLMConfig for a specific agent, merging overrides onto global defaults.

        Args:
            agent: "optimizer" or "analyzer"
        """
        override = getattr(self, agent, None)
        if override is None:
            return self

        return LLMConfig(
            provider=override.provider if override.provider is not None else self.provider,
            model=override.model if override.model is not None else self.model,
            api_base=override.api_base if override.api_base is not None else self.api_base,
            api_key=override.api_key if override.api_key is not None else self.api_key,
            temperature=override.temperature if override.temperature is not None else self.temperature,
            max_tokens=override.max_tokens if override.max_tokens is not None else self.max_tokens,
        )


class WorktreeConfig(BaseModel):
    """Git worktree management configuration."""

    base_dir: str = Field(
        default=".auto-bench-worktrees",
        description="Directory for worktrees, relative to project path",
    )
    cleanup_on_finish: bool = Field(default=True, description="Remove worktrees after optimization finishes")


class AutoBenchConfig(BaseModel):
    """Top-level configuration combining all sections."""

    project: ProjectConfig
    benchmark: BenchmarkConfig
    metrics: MetricsConfig
    optimization: OptimizationConfig = Field(default_factory=OptimizationConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    worktree: WorktreeConfig = Field(default_factory=WorktreeConfig)
