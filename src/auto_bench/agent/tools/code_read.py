"""Tool: read code files in the worktree."""

from __future__ import annotations

from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper

from auto_bench.agent.context import AgentContext


@function_tool
async def code_read(ctx: RunContextWrapper[AgentContext], file_path: str) -> str:
    """Read the contents of a file in the project.

    Args:
        file_path: Path relative to the project root.
    """
    wt = ctx.context.worktree_path
    full = (wt / file_path).resolve()

    # Security: ensure the path is within the worktree
    if not str(full).startswith(str(wt)):
        return f"Error: path {file_path} is outside the project directory."

    if not full.exists():
        return f"Error: file not found: {file_path}"

    if not full.is_file():
        return f"Error: {file_path} is not a file."

    try:
        content = full.read_text(errors="replace")
    except Exception as e:
        return f"Error reading file: {e}"

    # Truncate very large files
    max_chars = 100_000
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n... (truncated, total {len(content)} chars)"

    return content


@function_tool
async def list_files(ctx: RunContextWrapper[AgentContext], directory: str = ".", pattern: str = "**/*") -> str:
    """List files in the project matching a glob pattern.

    Args:
        directory: Directory relative to project root (default: root).
        pattern: Glob pattern to match files (default: all files).
    """
    wt = ctx.context.worktree_path
    base = (wt / directory).resolve()

    if not str(base).startswith(str(wt)):
        return "Error: directory is outside the project."

    if not base.is_dir():
        return f"Error: {directory} is not a directory."

    files = sorted(str(p.relative_to(wt)) for p in base.glob(pattern) if p.is_file())

    # Filter out git and worktree internals
    files = [f for f in files if not f.startswith(".git") and not f.startswith(".auto-bench")]

    if not files:
        return "No files found matching the pattern."

    return "\n".join(files[:500])
