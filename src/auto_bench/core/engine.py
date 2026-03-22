"""Main optimization engine — the heart of auto-bench."""

from __future__ import annotations

import logging
import signal
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from auto_bench.agent.analyzer_agent import AnalyzerAgent
from auto_bench.agent.model_provider import create_model_provider
from auto_bench.agent.optimizer_agent import OptimizerAgent
from auto_bench.bench.parser import ResultParser
from auto_bench.bench.runner import BenchmarkRunner
from auto_bench.config.schema import AutoBenchConfig
from auto_bench.core.decision import compute_composite_score, compute_improvements, is_improved
from auto_bench.core.state import IterationPhase, IterationState
from auto_bench.git.worktree import WorktreeManager
from auto_bench.history.models import BenchmarkResult, IterationRecord, OptimizationReport
from auto_bench.history.store import IterationStore

logger = logging.getLogger(__name__)
console = Console()


class OptimizationEngine:
    """Orchestrates the iterative optimization loop."""

    def __init__(
        self,
        config: AutoBenchConfig,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> None:
        self.config = config
        self.dry_run = dry_run
        self.verbose = verbose

        # Set up logging
        level = logging.DEBUG if verbose else logging.INFO
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S",
        )

        # Core components
        self.worktree_mgr = WorktreeManager(config.project.path, config.worktree)
        self.bench_runner = BenchmarkRunner(config.benchmark)
        self.result_parser = ResultParser(config.metrics)
        self.store = IterationStore(config.project.path / ".auto-bench-data")

        # Agents — resolve per-agent LLM configs and create providers
        optimizer_llm = config.llm.resolve_for("optimizer")
        analyzer_llm = config.llm.resolve_for("analyzer")

        # Share a single ModelProvider when both agents use the same
        # provider type and API endpoint
        optimizer_provider = create_model_provider(optimizer_llm)
        same_provider_type = optimizer_llm.provider == analyzer_llm.provider
        same_endpoint = (
            optimizer_llm.api_base == analyzer_llm.api_base
            and optimizer_llm.api_key == analyzer_llm.api_key
        )
        if same_provider_type and same_endpoint:
            analyzer_provider = optimizer_provider
        else:
            analyzer_provider = create_model_provider(analyzer_llm)

        self.optimizer = OptimizerAgent(optimizer_llm, model_provider=optimizer_provider)
        self.analyzer = AnalyzerAgent(analyzer_llm, model_provider=analyzer_provider)

        # State
        self.state = IterationState()
        self._interrupted = False

    async def run(self) -> OptimizationReport:
        """Execute the full optimization loop.

        Returns:
            OptimizationReport summarizing all iterations.
        """
        # Handle Ctrl+C gracefully
        original_handler = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._signal_handler)

        try:
            return await self._run_loop()
        finally:
            signal.signal(signal.SIGINT, original_handler)

    async def run_baseline_only(self) -> BenchmarkResult:
        """Run the baseline benchmark without any optimization."""
        console.print("\n[bold]Running baseline benchmark...[/bold]")
        raw = await self.bench_runner.run(self.config.project.path)
        result = self.result_parser.parse(raw, self.config.project.path)
        self._print_metrics("Baseline", result)
        return result

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> OptimizationReport:
        """The core optimization loop."""
        definitions = self.config.metrics.definitions

        # 1. Setup
        self.state.set(IterationPhase.INIT)
        console.print(f"\n[bold cyan]Auto-Benchmark[/bold cyan] — optimizing [bold]{self.config.project.name}[/bold]")
        console.print(f"Max iterations: {self.config.optimization.max_iterations}")
        console.print(f"Max no-improve: {self.config.optimization.max_no_improve}")

        await self.worktree_mgr.setup(self.config.project.base_branch)
        await self.store.initialize()

        # 2. Baseline benchmark
        self.state.set(IterationPhase.BASELINE)
        console.print("\n[bold]Running baseline benchmark...[/bold]")
        baseline_raw = await self.bench_runner.run(self.config.project.path)
        baseline = self.result_parser.parse(baseline_raw, self.config.project.path)
        self._print_metrics("Baseline", baseline)

        if not baseline.metrics:
            console.print("[bold red]Error:[/bold red] No metrics extracted from baseline. Check your config.")
            return OptimizationReport(project_name=self.config.project.name, stop_reason="no_baseline_metrics")

        baseline_score = compute_composite_score(baseline, definitions)
        best_result = baseline
        best_score = baseline_score
        records: list[IterationRecord] = []
        history_lines: list[str] = []

        # 3. Iteration loop
        while self.state.iteration < self.config.optimization.max_iterations and not self._interrupted:
            iteration_id = self.state.next_iteration()
            console.print(f"\n{'='*60}")
            console.print(f"[bold yellow]Iteration {iteration_id}[/bold yellow]")
            console.print(f"{'='*60}")

            record = IterationRecord(
                iteration_id=iteration_id,
                branch_name=f"auto-bench/iter-{iteration_id:03d}",
                worktree_path="",
                status="running",
                baseline_metrics=best_result.to_dict(),
            )

            try:
                # 3a. Create worktree
                self.state.set(IterationPhase.CREATE_WORKTREE)
                console.print("  Creating worktree...")
                wt = await self.worktree_mgr.create_iteration_worktree(iteration_id)
                record.worktree_path = str(wt.path)

                # 3b. Run optimizer agent
                self.state.set(IterationPhase.OPTIMIZE)
                record.status = "optimizing"
                console.print("  Running optimizer agent...")
                history_summary = "\n".join(history_lines[-10:])  # Last 10 iterations

                if self.dry_run:
                    console.print("  [dim](dry run — skipping code modification)[/dim]")
                    proposal_result = None
                else:
                    proposal_result = await self.optimizer.propose_and_apply(
                        worktree_path=wt.path,
                        config=self.config,
                        baseline_metrics=best_result.to_dict(),
                        iteration_id=iteration_id,
                        history_summary=history_summary,
                    )
                    record.hypothesis = proposal_result.hypothesis
                    record.changes_summary = proposal_result.changes_summary
                    record.files_changed = proposal_result.files_modified
                    console.print(f"  Hypothesis: {proposal_result.hypothesis}")

                # 3c. Get diff
                diff = await self.worktree_mgr.get_diff(wt.path)
                if not diff.strip():
                    # Check for untracked files
                    status = await self.worktree_mgr.get_status(wt.path)
                    if not status.strip():
                        console.print("  [dim]No changes made. Reverting.[/dim]")
                        record.status = "reverted"
                        record.decision = "revert"
                        record.llm_reasoning = "No code changes were made."
                        await self.worktree_mgr.revert_iteration(iteration_id)
                        self.state.record_no_improvement()
                        records.append(record)
                        history_lines.append(
                            f"Iteration {iteration_id}: REVERTED — no changes made."
                        )
                        continue
                record.diff = diff

                # 3d. Run benchmark in worktree
                self.state.set(IterationPhase.BENCHMARK)
                record.status = "benchmarking"
                console.print("  Running benchmark...")
                bench_raw = await self.bench_runner.run(wt.path)
                current = self.result_parser.parse(bench_raw, wt.path)
                self._print_metrics("  Current", current)

                record.result_metrics = current.to_dict()
                current_score = compute_composite_score(current, definitions)
                record.composite_score_before = best_score
                record.composite_score_after = current_score

                # 3e. Analyze results
                self.state.set(IterationPhase.ANALYZE)
                record.status = "analyzing"
                console.print("  Analyzing results...")
                improvements = compute_improvements(best_result, current, definitions)
                record.improvement = improvements

                analysis = await self.analyzer.analyze_results(
                    config=self.config,
                    baseline=best_result,
                    current=current,
                    diff=diff,
                    hypothesis=record.hypothesis,
                    worktree_path=wt.path,
                    iteration_id=iteration_id,
                )
                record.llm_reasoning = analysis.reasoning

                # 3f. Decision
                self.state.set(IterationPhase.DECIDE)

                # Use both algorithmic check and LLM recommendation
                algo_improved = is_improved(best_result, current, definitions)
                llm_decision = analysis.decision

                if algo_improved and llm_decision == "keep":
                    decision = "keep"
                elif not algo_improved and llm_decision == "revert":
                    decision = "revert"
                elif algo_improved:
                    # Algo says improved but LLM says revert — trust algo
                    decision = "keep"
                    record.llm_reasoning += " [Note: LLM recommended revert but metrics improved.]"
                else:
                    # Algo says no improve, LLM says keep — trust algo
                    decision = "revert"
                    record.llm_reasoning += " [Note: LLM recommended keep but metrics did not improve.]"

                record.decision = decision

                if decision == "keep":
                    self.state.set(IterationPhase.SAVE)
                    console.print("  [bold green]✓ Keeping changes[/bold green]")
                    await self.worktree_mgr.commit_changes(wt.path, record.changes_summary)
                    await self.worktree_mgr.accept_iteration(iteration_id)
                    best_result = current
                    best_score = current_score
                    record.status = "success"
                    self.state.record_improvement()
                    history_lines.append(
                        f"Iteration {iteration_id}: KEPT — {record.hypothesis} — "
                        f"improvements: {improvements}"
                    )
                else:
                    self.state.set(IterationPhase.REVERT)
                    console.print("  [bold red]✗ Reverting changes[/bold red]")
                    await self.worktree_mgr.revert_iteration(iteration_id)
                    record.status = "reverted"
                    self.state.record_no_improvement()
                    history_lines.append(
                        f"Iteration {iteration_id}: REVERTED — {record.hypothesis} — "
                        f"reason: {analysis.reasoning[:100]}"
                    )

                # Print improvement details
                for metric_name, imp in improvements.items():
                    direction = "↑" if imp > 0 else "↓"
                    console.print(f"    {metric_name}: {direction} {abs(imp)*100:.2f}%")

            except Exception as e:
                logger.exception("Error in iteration %d", iteration_id)
                record.status = "failed"
                record.error_message = str(e)
                console.print(f"  [bold red]Error: {e}[/bold red]")
                # Try to clean up the worktree
                try:
                    await self.worktree_mgr.revert_iteration(iteration_id)
                except Exception:
                    pass
                self.state.record_no_improvement()
                history_lines.append(f"Iteration {iteration_id}: FAILED — {e}")

            # Save record
            records.append(record)
            await self.store.save_iteration(record)

            # 3g. Check stopping conditions
            self.state.set(IterationPhase.CHECK_STOP)
            if self.state.no_improve_count >= self.config.optimization.max_no_improve:
                console.print(
                    f"\n[yellow]Stopping: {self.state.no_improve_count} consecutive iterations "
                    f"without improvement.[/yellow]"
                )
                break

        # 4. Generate report
        self.state.set(IterationPhase.REPORT)
        stop_reason = "max_iterations"
        if self._interrupted:
            stop_reason = "user_interrupted"
        elif self.state.no_improve_count >= self.config.optimization.max_no_improve:
            stop_reason = "no_improvement_convergence"

        report = OptimizationReport(
            project_name=self.config.project.name,
            total_iterations=self.state.iteration,
            successful_iterations=sum(1 for r in records if r.status == "success"),
            reverted_iterations=sum(1 for r in records if r.status == "reverted"),
            failed_iterations=sum(1 for r in records if r.status == "failed"),
            baseline_metrics=baseline.to_dict(),
            final_metrics=best_result.to_dict(),
            best_score=best_score,
            baseline_score=baseline_score,
            iterations=records,
            stop_reason=stop_reason,
        )

        self._print_report(report)

        # 5. Cleanup
        if self.config.worktree.cleanup_on_finish:
            console.print("\n[dim]Cleaning up worktrees...[/dim]")
            await self.worktree_mgr.cleanup()

        self.state.set(IterationPhase.DONE)
        return report

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _print_metrics(self, label: str, result: BenchmarkResult) -> None:
        """Print metrics in a nice table."""
        table = Table(title=f"{label} Metrics", show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green", justify="right")
        table.add_column("Direction", style="dim")

        for m in result.metrics:
            table.add_row(m.name, f"{m.value:.4f}", m.direction)

        console.print(table)

    def _print_report(self, report: OptimizationReport) -> None:
        """Print the final optimization report."""
        console.print(f"\n{'='*60}")
        console.print("[bold cyan]Optimization Report[/bold cyan]")
        console.print(f"{'='*60}")
        console.print(f"Project: {report.project_name}")
        console.print(f"Total iterations: {report.total_iterations}")
        console.print(f"Successful: {report.successful_iterations}")
        console.print(f"Reverted: {report.reverted_iterations}")
        console.print(f"Failed: {report.failed_iterations}")
        console.print(f"Stop reason: {report.stop_reason}")
        console.print(f"Baseline score: {report.baseline_score:.4f}")
        console.print(f"Best score: {report.best_score:.4f}")

        if report.baseline_score != 0:
            overall_improvement = (report.best_score - report.baseline_score) / abs(report.baseline_score) * 100
            console.print(f"Overall improvement: {overall_improvement:+.2f}%")

        # Per-metric comparison
        console.print("\n[bold]Metric Comparison:[/bold]")
        table = Table(show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Baseline", justify="right")
        table.add_column("Final", justify="right")
        table.add_column("Change", justify="right")

        for name, base_val in report.baseline_metrics.items():
            final_val = report.final_metrics.get(name, base_val)
            if base_val != 0:
                change = (final_val - base_val) / abs(base_val) * 100
                change_str = f"{change:+.2f}%"
            else:
                change_str = "N/A"
            table.add_row(name, f"{base_val:.4f}", f"{final_val:.4f}", change_str)

        console.print(table)

    def _signal_handler(self, signum, frame) -> None:
        """Handle Ctrl+C gracefully."""
        if self._interrupted:
            console.print("\n[bold red]Force exit.[/bold red]")
            sys.exit(1)
        console.print("\n[yellow]Interrupt received. Finishing current iteration and stopping...[/yellow]")
        self._interrupted = True
