"""Git worktree management for isolated iteration experiments."""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from auto_bench.config.schema import WorktreeConfig

logger = logging.getLogger(__name__)


@dataclass
class WorktreeInfo:
    """Information about a single worktree."""

    path: Path
    branch_name: str
    base_commit: str
    iteration_id: int


class WorktreeManager:
    """Manage git worktrees for parallel experimentation.

    Branch strategy:
        main (user's branch, untouched)
        └── auto-bench/best          <- current best (advances with successful iterations)
            ├── auto-bench/iter-001   <- iteration 1 (merged if improved, deleted if not)
            ├── auto-bench/iter-002
            └── ...
    """

    BEST_BRANCH = "auto-bench/best"
    ITER_BRANCH_PREFIX = "auto-bench/iter-"
    DATA_DIR = ".auto-bench-data"

    def __init__(self, project_path: Path, config: WorktreeConfig) -> None:
        self.project_path = project_path.resolve()
        self.config = config
        self.worktree_base = self.project_path / config.base_dir
        self._active_worktrees: dict[int, WorktreeInfo] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def setup(self, base_branch: str = "main") -> str:
        """Initialize worktree infrastructure. Returns the baseline commit hash.

        1. Verify the project is a git repo.
        2. Create the `auto-bench/best` branch from `base_branch` if it doesn't exist.
        3. Create the worktree base directory.
        """
        await self._ensure_git_repo()

        # Make sure we're on the base branch or it exists
        branches = await self._git("branch", "--list", "--format=%(refname:short)")
        branch_list = branches.strip().splitlines()

        if self.BEST_BRANCH not in branch_list:
            # Create best branch from base_branch
            base_commit = await self._git("rev-parse", base_branch)
            await self._git("branch", self.BEST_BRANCH, base_commit.strip())
            logger.info("Created branch %s from %s", self.BEST_BRANCH, base_branch)
        else:
            logger.info("Branch %s already exists", self.BEST_BRANCH)

        self.worktree_base.mkdir(parents=True, exist_ok=True)

        # Ensure data directory exists
        (self.project_path / self.DATA_DIR).mkdir(parents=True, exist_ok=True)

        best_commit = await self._git("rev-parse", self.BEST_BRANCH)
        return best_commit.strip()

    async def create_iteration_worktree(self, iteration_id: int) -> WorktreeInfo:
        """Create a new worktree for an iteration.

        1. Create branch `auto-bench/iter-{id}` from `auto-bench/best`.
        2. `git worktree add <path> <branch>`.
        3. Return WorktreeInfo.
        """
        branch_name = f"{self.ITER_BRANCH_PREFIX}{iteration_id:03d}"
        wt_path = self.worktree_base / f"iter-{iteration_id:03d}"

        # Clean up if stale worktree exists
        if wt_path.exists():
            await self._remove_worktree(wt_path)

        # Get current best commit
        best_commit = (await self._git("rev-parse", self.BEST_BRANCH)).strip()

        # Create branch from best
        branches = await self._git("branch", "--list", "--format=%(refname:short)")
        if branch_name in branches.strip().splitlines():
            await self._git("branch", "-D", branch_name)

        await self._git("branch", branch_name, self.BEST_BRANCH)

        # Create worktree
        await self._git("worktree", "add", str(wt_path), branch_name)

        info = WorktreeInfo(
            path=wt_path,
            branch_name=branch_name,
            base_commit=best_commit,
            iteration_id=iteration_id,
        )
        self._active_worktrees[iteration_id] = info
        logger.info("Created worktree for iteration %d at %s", iteration_id, wt_path)
        return info

    async def commit_changes(self, worktree_path: Path, message: str) -> str:
        """Stage all changes and commit in the given worktree. Returns commit hash."""
        await self._git_in(worktree_path, "add", "-A")
        await self._git_in(worktree_path, "commit", "-m", message, "--allow-empty")
        commit_hash = (await self._git_in(worktree_path, "rev-parse", "HEAD")).strip()
        logger.info("Committed changes in %s: %s", worktree_path.name, commit_hash[:8])
        return commit_hash

    async def accept_iteration(self, iteration_id: int) -> str:
        """Accept an iteration: merge its branch into auto-bench/best.

        Returns the new best commit hash.
        """
        info = self._active_worktrees.get(iteration_id)
        if info is None:
            raise ValueError(f"No active worktree for iteration {iteration_id}")

        # Remove worktree first (can't merge while worktree is active on that branch)
        await self._remove_worktree(info.path)

        # Fast-forward merge into best branch
        # We use a temporary checkout-free approach: update the best ref
        iter_commit = (await self._git("rev-parse", info.branch_name)).strip()
        await self._git("update-ref", f"refs/heads/{self.BEST_BRANCH}", iter_commit)

        # Clean up iteration branch
        await self._git("branch", "-D", info.branch_name)

        del self._active_worktrees[iteration_id]
        logger.info("Accepted iteration %d, best branch updated to %s", iteration_id, iter_commit[:8])
        return iter_commit

    async def revert_iteration(self, iteration_id: int) -> None:
        """Revert an iteration: remove worktree and delete branch."""
        info = self._active_worktrees.get(iteration_id)
        if info is None:
            raise ValueError(f"No active worktree for iteration {iteration_id}")

        await self._remove_worktree(info.path)

        # Delete iteration branch
        try:
            await self._git("branch", "-D", info.branch_name)
        except RuntimeError:
            logger.warning("Could not delete branch %s", info.branch_name)

        del self._active_worktrees[iteration_id]
        logger.info("Reverted iteration %d", iteration_id)

    async def get_diff(self, worktree_path: Path) -> str:
        """Get the diff of all changes in a worktree relative to its base."""
        return await self._git_in(worktree_path, "diff", "HEAD")

    async def get_staged_diff(self, worktree_path: Path) -> str:
        """Get diff of staged changes."""
        return await self._git_in(worktree_path, "diff", "--cached")

    async def get_status(self, worktree_path: Path) -> str:
        """Get git status in worktree."""
        return await self._git_in(worktree_path, "status", "--short")

    async def get_best_commit(self) -> str:
        """Get the current best branch commit hash."""
        return (await self._git("rev-parse", self.BEST_BRANCH)).strip()

    async def cleanup(self) -> None:
        """Remove all auto-bench worktrees and branches."""
        # List and remove worktrees
        worktree_output = await self._git("worktree", "list", "--porcelain")
        for line in worktree_output.splitlines():
            if line.startswith("worktree "):
                wt_path = Path(line.split(" ", 1)[1])
                if str(self.worktree_base) in str(wt_path):
                    await self._remove_worktree(wt_path)

        # Remove worktree base directory
        if self.worktree_base.exists():
            shutil.rmtree(self.worktree_base, ignore_errors=True)

        # Delete all auto-bench branches
        branches = await self._git("branch", "--list", "--format=%(refname:short)")
        for branch in branches.strip().splitlines():
            branch = branch.strip()
            if branch.startswith("auto-bench/"):
                try:
                    await self._git("branch", "-D", branch)
                    logger.info("Deleted branch %s", branch)
                except RuntimeError:
                    logger.warning("Could not delete branch %s", branch)

        self._active_worktrees.clear()
        logger.info("Cleanup complete")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_git_repo(self) -> None:
        """Verify the project path is a git repository."""
        git_dir = self.project_path / ".git"
        if not git_dir.exists():
            raise RuntimeError(f"{self.project_path} is not a git repository (no .git directory)")

    async def _git(self, *args: str) -> str:
        """Run a git command in the project directory."""
        return await self._run_cmd("git", *args, cwd=self.project_path)

    async def _git_in(self, worktree_path: Path, *args: str) -> str:
        """Run a git command in a specific worktree directory."""
        return await self._run_cmd("git", *args, cwd=worktree_path)

    async def _run_cmd(self, *args: str, cwd: Path) -> str:
        """Run a subprocess command and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode().strip()
            cmd_str = " ".join(args)
            raise RuntimeError(f"Command failed ({proc.returncode}): {cmd_str}\n{err_msg}")

        return stdout.decode()

    async def _remove_worktree(self, wt_path: Path) -> None:
        """Remove a git worktree."""
        try:
            await self._git("worktree", "remove", str(wt_path), "--force")
        except RuntimeError:
            # Fallback: manual removal
            if wt_path.exists():
                shutil.rmtree(wt_path, ignore_errors=True)
            try:
                await self._git("worktree", "prune")
            except RuntimeError:
                pass
