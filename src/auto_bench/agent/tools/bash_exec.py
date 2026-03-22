"""Tool: execute shell commands in the worktree."""

from __future__ import annotations

import asyncio

from agents import function_tool
from agents.run_context import RunContextWrapper

from auto_bench.agent.context import AgentContext


@function_tool
async def bash_exec(
    ctx: RunContextWrapper[AgentContext],
    command: str,
    timeout: int = 60,
) -> str:
    """Execute a shell command in the project directory.

    Use this for running tests, checking syntax, installing dependencies, etc.
    Do NOT use this for destructive operations on the git repository.

    Args:
        command: Shell command to execute.
        timeout: Maximum execution time in seconds (default: 60).
    """
    wt = ctx.context.worktree_path

    # Block dangerous commands
    dangerous = ["rm -rf /", "rm -rf /*", "mkfs", "dd if=", ":(){:|:&};:"]
    for d in dangerous:
        if d in command:
            return f"Error: command blocked for safety: {command}"

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(wt),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        return f"Error: command timed out after {timeout}s: {command}"

    stdout = stdout_bytes.decode(errors="replace")
    stderr = stderr_bytes.decode(errors="replace")

    # Truncate large outputs
    max_len = 50_000
    if len(stdout) > max_len:
        stdout = stdout[:max_len] + "\n... (stdout truncated)"
    if len(stderr) > max_len:
        stderr = stderr[:max_len] + "\n... (stderr truncated)"

    parts = [f"Exit code: {proc.returncode}"]
    if stdout.strip():
        parts.append(f"STDOUT:\n{stdout}")
    if stderr.strip():
        parts.append(f"STDERR:\n{stderr}")

    return "\n".join(parts)
