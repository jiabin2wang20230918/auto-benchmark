"""Report generation and display."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.table import Table

from auto_bench.history.store import IterationStore

logger = logging.getLogger(__name__)
console = Console()


class Reporter:
    """Generate and display optimization reports."""

    def __init__(self, project_path: Path) -> None:
        self.store = IterationStore(project_path / ".auto-bench-data")

    async def print_report(self) -> None:
        """Print the optimization report to the terminal."""
        report = await self.store.load_report()
        if report is None:
            console.print("[yellow]No optimization report found. Run `auto-bench run` first.[/yellow]")
            return

        console.print(f"\n{'='*60}")
        console.print(f"[bold cyan]Optimization Report: {report.project_name}[/bold cyan]")
        console.print(f"{'='*60}")
        console.print(f"Total iterations: {report.total_iterations}")
        console.print(f"Successful: [green]{report.successful_iterations}[/green]")
        console.print(f"Reverted: [red]{report.reverted_iterations}[/red]")
        console.print(f"Failed: [red]{report.failed_iterations}[/red]")
        console.print(f"Stop reason: {report.stop_reason}")

        # Metrics comparison table
        console.print("\n[bold]Metrics Comparison:[/bold]")
        table = Table(show_header=True)
        table.add_column("Metric", style="cyan")
        table.add_column("Baseline", justify="right")
        table.add_column("Final", justify="right")
        table.add_column("Change", justify="right")

        for name, base_val in report.baseline_metrics.items():
            final_val = report.final_metrics.get(name, base_val)
            if base_val != 0:
                pct = (final_val - base_val) / abs(base_val) * 100
                change_str = f"[green]{pct:+.2f}%[/green]" if pct > 0 else f"[red]{pct:+.2f}%[/red]"
            else:
                change_str = "N/A"
            table.add_row(name, f"{base_val:.4f}", f"{final_val:.4f}", change_str)

        console.print(table)

        # Iteration history
        console.print("\n[bold]Iteration History:[/bold]")
        iter_table = Table(show_header=True)
        iter_table.add_column("#", style="dim", justify="right")
        iter_table.add_column("Status", justify="center")
        iter_table.add_column("Decision", justify="center")
        iter_table.add_column("Hypothesis")
        iter_table.add_column("Score", justify="right")

        for it in report.iterations:
            status_style = {
                "success": "[green]success[/green]",
                "reverted": "[yellow]reverted[/yellow]",
                "failed": "[red]failed[/red]",
            }.get(it.status, it.status)

            decision_style = {
                "keep": "[green]keep[/green]",
                "revert": "[red]revert[/red]",
            }.get(it.decision or "", it.decision or "-")

            score_str = f"{it.composite_score_after:.4f}" if it.composite_score_after is not None else "-"
            hypothesis_short = (it.hypothesis[:60] + "...") if len(it.hypothesis) > 60 else it.hypothesis

            iter_table.add_row(
                str(it.iteration_id),
                status_style,
                decision_style,
                hypothesis_short,
                score_str,
            )

        console.print(iter_table)

    async def print_iteration_detail(self, iteration_id: int) -> None:
        """Print detailed information about a specific iteration."""
        record = await self.store.load_iteration(iteration_id)
        if record is None:
            console.print(f"[yellow]Iteration {iteration_id} not found.[/yellow]")
            return

        console.print(f"\n[bold cyan]Iteration {record.iteration_id} Details[/bold cyan]")
        console.print(f"Status: {record.status}")
        console.print(f"Decision: {record.decision}")
        console.print(f"Branch: {record.branch_name}")
        console.print(f"Hypothesis: {record.hypothesis}")
        console.print(f"Changes: {record.changes_summary}")

        if record.files_changed:
            console.print(f"Files modified: {', '.join(record.files_changed)}")

        if record.improvement:
            console.print("\n[bold]Metric Improvements:[/bold]")
            for name, imp in record.improvement.items():
                direction = "↑" if imp > 0 else "↓"
                console.print(f"  {name}: {direction} {abs(imp)*100:.2f}%")

        if record.llm_reasoning:
            console.print(f"\n[bold]LLM Analysis:[/bold]\n{record.llm_reasoning}")

        if record.diff:
            console.print(f"\n[bold]Diff:[/bold]\n{record.diff[:3000]}")
