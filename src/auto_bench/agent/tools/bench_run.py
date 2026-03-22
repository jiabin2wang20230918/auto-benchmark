"""Tool: run benchmark command."""

from __future__ import annotations

from agents import function_tool
from agents.run_context import RunContextWrapper

from auto_bench.agent.context import AgentContext
from auto_bench.bench.runner import BenchmarkRunner


@function_tool
async def bench_run(ctx: RunContextWrapper[AgentContext]) -> str:
    """Run the project benchmark and return raw output.

    This executes the configured benchmark command in the project directory.
    Use this after making code changes to measure their impact.
    """
    config = ctx.context.config.benchmark
    runner = BenchmarkRunner(config)

    try:
        result = await runner.run(ctx.context.worktree_path)
    except TimeoutError as e:
        return f"Benchmark timed out: {e}"
    except Exception as e:
        return f"Benchmark execution error: {e}"

    parts = [f"Exit code: {result.exit_code}", f"Duration: {result.duration_seconds:.1f}s"]
    if result.stdout.strip():
        parts.append(f"Output:\n{result.stdout}")
    if result.stderr.strip():
        parts.append(f"Stderr:\n{result.stderr}")

    return "\n".join(parts)
