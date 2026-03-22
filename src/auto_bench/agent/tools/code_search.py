"""Tool: search code in the worktree."""

from __future__ import annotations

import asyncio
import fnmatch
from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper

from auto_bench.agent.context import AgentContext


@function_tool
async def code_search(
    ctx: RunContextWrapper[AgentContext],
    pattern: str,
    file_glob: str = "**/*",
    max_results: int = 50,
) -> str:
    """Search for a regex pattern in project files.

    Returns matching lines with file paths and line numbers.

    Args:
        pattern: Regular expression pattern to search for.
        file_glob: Glob pattern to filter which files to search (default: all files).
        max_results: Maximum number of matching lines to return.
    """
    wt = ctx.context.worktree_path

    # Use grep for speed if available
    try:
        proc = await asyncio.create_subprocess_exec(
            "grep", "-rn", "--include", file_glob, "-E", pattern, ".",
            cwd=str(wt),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        lines = stdout.decode(errors="replace").strip().splitlines()

        # Filter out .git and .auto-bench
        lines = [l for l in lines if not l.startswith("./.git") and ".auto-bench" not in l]

        if not lines:
            return "No matches found."

        if len(lines) > max_results:
            lines = lines[:max_results]
            lines.append(f"... (truncated, showing {max_results} of more results)")

        return "\n".join(lines)

    except (FileNotFoundError, asyncio.TimeoutError):
        return "Error: search command failed or timed out."
