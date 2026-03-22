"""Tool: git operations in the worktree."""

from __future__ import annotations

import asyncio

from agents import function_tool
from agents.run_context import RunContextWrapper

from auto_bench.agent.context import AgentContext


@function_tool
async def git_diff(ctx: RunContextWrapper[AgentContext]) -> str:
    """Show all uncommitted changes in the project (git diff + untracked files)."""
    wt = ctx.context.worktree_path

    # Staged + unstaged changes
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "HEAD",
        cwd=str(wt),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    diff = stdout.decode(errors="replace")

    # Also show untracked files
    proc2 = await asyncio.create_subprocess_exec(
        "git", "status", "--short",
        cwd=str(wt),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout2, _ = await proc2.communicate()
    status = stdout2.decode(errors="replace")

    parts = []
    if status.strip():
        parts.append(f"Status:\n{status}")
    if diff.strip():
        parts.append(f"Diff:\n{diff}")

    return "\n".join(parts) if parts else "No changes."


@function_tool
async def git_log(ctx: RunContextWrapper[AgentContext], n: int = 10) -> str:
    """Show recent git commit history.

    Args:
        n: Number of recent commits to show (default: 10).
    """
    wt = ctx.context.worktree_path

    proc = await asyncio.create_subprocess_exec(
        "git", "log", f"-{n}", "--oneline", "--decorate",
        cwd=str(wt),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode(errors="replace") or "No commit history."
