"""Diff utilities for comparing code changes."""

from __future__ import annotations

import asyncio
from pathlib import Path


async def get_file_diff(worktree_path: Path, file_path: str) -> str:
    """Get the diff for a specific file in a worktree."""
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "HEAD", "--", file_path,
        cwd=str(worktree_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()


async def get_changed_files(worktree_path: Path) -> list[str]:
    """List files changed in the worktree relative to HEAD."""
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", "HEAD", "--name-only",
        cwd=str(worktree_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return [f for f in stdout.decode().strip().splitlines() if f]


async def get_diff_between_commits(project_path: Path, commit_a: str, commit_b: str) -> str:
    """Get the diff between two commits."""
    proc = await asyncio.create_subprocess_exec(
        "git", "diff", commit_a, commit_b,
        cwd=str(project_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()
