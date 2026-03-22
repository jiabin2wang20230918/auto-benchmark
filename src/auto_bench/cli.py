"""CLI entry points for auto-bench."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from dotenv import load_dotenv


@click.group()
@click.version_option(package_name="auto-bench")
def cli() -> None:
    """Auto-Benchmark: LLM-driven automated benchmark tuning tool."""
    load_dotenv()


@cli.command()
@click.argument("config_path", type=click.Path(exists=True, path_type=Path))
@click.option("--max-iter", type=int, default=None, help="Override max iterations.")
@click.option("--dry-run", is_flag=True, help="Analyze only, do not modify code.")
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output.")
def run(config_path: Path, max_iter: int | None, dry_run: bool, verbose: bool) -> None:
    """Run the automated optimization loop."""
    from auto_bench.config import load_config
    from auto_bench.core.engine import OptimizationEngine

    config = load_config(config_path)
    if max_iter is not None:
        config.optimization.max_iterations = max_iter

    engine = OptimizationEngine(config, dry_run=dry_run, verbose=verbose)
    report = asyncio.run(engine.run())

    click.echo(f"\nOptimization finished. Total iterations: {report.total_iterations}")
    click.echo(f"Best composite score: {report.best_score:.4f}")


@cli.command()
@click.argument("config_path", type=click.Path(exists=True, path_type=Path))
def baseline(config_path: Path) -> None:
    """Run baseline benchmark only and display results."""
    from auto_bench.config import load_config
    from auto_bench.core.engine import OptimizationEngine

    config = load_config(config_path)
    engine = OptimizationEngine(config)
    result = asyncio.run(engine.run_baseline_only())

    click.echo("\n--- Baseline Results ---")
    for m in result.metrics:
        click.echo(f"  {m.name}: {m.value}")


@cli.command()
@click.argument("project_path", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None, help="Output config file path.")
def init(project_path: Path, output: Path | None) -> None:
    """Interactively generate a configuration file for a project."""
    if output is None:
        output = Path(f"configs/{project_path.name}.yaml")

    output.parent.mkdir(parents=True, exist_ok=True)

    import yaml

    from auto_bench.config.schema import AutoBenchConfig, BenchmarkConfig, MetricsConfig, ProjectConfig

    name = click.prompt("Project name", default=project_path.name)
    bench_cmd = click.prompt("Benchmark command", default="python run_benchmark.py")
    metric_source = click.prompt("Metrics source", type=click.Choice(["json", "regex", "stdout_kv"]), default="json")

    config = AutoBenchConfig(
        project=ProjectConfig(name=name, path=project_path.resolve()),
        benchmark=BenchmarkConfig(command=bench_cmd),
        metrics=MetricsConfig(source=metric_source, definitions=[]),
    )

    with open(output, "w") as f:
        yaml.dump(config.model_dump(mode="json"), f, default_flow_style=False, sort_keys=False)

    click.echo(f"Config written to {output}")
    click.echo("Edit the file to add metric definitions and adjust settings.")


@cli.command()
@click.argument("config_path", type=click.Path(exists=True, path_type=Path))
def report(config_path: Path) -> None:
    """View optimization history report."""
    from auto_bench.config import load_config
    from auto_bench.report.reporter import Reporter

    config = load_config(config_path)
    reporter = Reporter(config.project.path)
    asyncio.run(reporter.print_report())


@cli.command()
@click.argument("config_path", type=click.Path(exists=True, path_type=Path))
@click.confirmation_option(prompt="This will remove all worktrees and temp branches. Continue?")
def cleanup(config_path: Path) -> None:
    """Clean up all worktrees and temporary branches."""
    from auto_bench.config import load_config
    from auto_bench.git.worktree import WorktreeManager

    config = load_config(config_path)
    mgr = WorktreeManager(config.project.path, config.worktree)
    asyncio.run(mgr.cleanup())
    click.echo("Cleanup complete.")
