"""Tool: edit code files in the worktree."""

from __future__ import annotations

from pathlib import Path

from agents import function_tool
from agents.run_context import RunContextWrapper

from auto_bench.agent.context import AgentContext


@function_tool
async def code_edit(
    ctx: RunContextWrapper[AgentContext],
    file_path: str,
    old_content: str,
    new_content: str,
) -> str:
    """Replace a specific section of code in a file with new content.

    The old_content must match exactly (including whitespace and indentation).
    Use code_read first to see the exact contents.

    Args:
        file_path: Path relative to the project root.
        old_content: Exact text to find and replace (must be unique in the file).
        new_content: Text to replace it with.
    """
    wt = ctx.context.worktree_path
    full = (wt / file_path).resolve()

    if not str(full).startswith(str(wt)):
        return "Error: path is outside the project directory."

    if not full.exists():
        return f"Error: file not found: {file_path}"

    content = full.read_text()

    count = content.count(old_content)
    if count == 0:
        return (
            f"Error: old_content not found in {file_path}. "
            "Make sure you copied the exact text including whitespace."
        )
    if count > 1:
        return (
            f"Error: old_content appears {count} times in {file_path}. "
            "Provide more surrounding context to make it unique."
        )

    new_file_content = content.replace(old_content, new_content, 1)
    full.write_text(new_file_content)

    return f"Successfully edited {file_path}"


@function_tool
async def code_write(
    ctx: RunContextWrapper[AgentContext],
    file_path: str,
    content: str,
) -> str:
    """Write or overwrite a file with the given content.

    Use this to create new files or completely replace existing ones.
    For partial edits, prefer code_edit.

    Args:
        file_path: Path relative to the project root.
        content: Complete file content to write.
    """
    wt = ctx.context.worktree_path
    full = (wt / file_path).resolve()

    if not str(full).startswith(str(wt)):
        return "Error: path is outside the project directory."

    # Create parent directories
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)

    return f"Successfully wrote {file_path} ({len(content)} chars)"
