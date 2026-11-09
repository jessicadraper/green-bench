import re
import shlex
import shutil
import sys
import time
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Optional

import typer
import typer.core
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from green_bench import __version__
from green_bench.analysis import AnalysisEngine
from green_bench.environment import EnvironmentManager
from green_bench.measurement import BenchmarkError, MeasurementWrapper
from green_bench.orchestrator import ExperimentOrchestrator
from green_bench.results import FOREIGN, HAS_RESULTS, classify, describe

console = Console()

_SUBCOMMANDS = ("compare", "demo")


class _DefaultToCompare(typer.core.TyperGroup):
    """`green-bench --name ...` is shorthand for `green-bench compare --name ...`."""

    def parse_args(self, ctx, args):
        if args and args[0] not in _SUBCOMMANDS and args[0] not in ctx.help_option_names:
            args = ["compare", *args]
        return super().parse_args(ctx, args)


app = typer.Typer(
    cls=_DefaultToCompare,
    add_completion=False,
    help="Green Software Benchmarking CLI Tool.\n\n"
         "Run `green-bench demo` to try it on a bundled example, or `green-bench compare --help` "
         "(or just `green-bench --name ...`) to compare two versions of your own project.",
)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _version_callback(value: bool):
    if value:
        typer.echo(f"green-bench {__version__}")
        raise typer.Exit()


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _confirm_overwrite(results_dir: Path, resume: bool, overwrite: bool) -> None:
    """Decide what to do with an existing results folder (before anything is created or deleted).

    Nothing is deleted here: the orchestrator clears the folder after pre-flight has passed.
    """
    if resume:
        return
    state = classify(results_dir)
    if state == FOREIGN:
        raise BenchmarkError(
            f"{results_dir} exists but does not look like a GreenBench results folder, so it will "
            "not be touched. Choose a different --name or --output."
        )
    if state != HAS_RESULTS or overwrite:  # missing or empty folders are simply reused
        return
    if not _is_interactive():
        raise BenchmarkError(
            f"Results folder already exists: {results_dir}. Use --overwrite to replace it "
            "or --resume to continue the unfinished experiment."
        )
    console.print(f"[yellow]Results folder already exists:[/yellow] {escape(str(results_dir.resolve()))}")
    console.print(f"  contains {describe(results_dir)}")
    console.print("  (To continue an unfinished experiment instead, answer n and run again with --resume.)")
    if not typer.confirm("Delete these previous results and start over?", default=False):
        console.print("Aborted. The existing results were not changed.")
        raise typer.Exit(1)


def _validate_name(value: str) -> str:
    if not _NAME_RE.match(value):
        raise typer.BadParameter(
            "Use letters, digits, '.', '_' or '-' only (it becomes a folder name)."
        )
    return value


@app.command()
def compare(
    name: str = typer.Option(..., "--name", help="Name of the benchmark (used as the results folder name)",
                             callback=_validate_name),
    base: Path = typer.Option(..., "--base", "-b", help="Directory containing the baseline version of the project"),
    compare: Path = typer.Option(..., "--compare", "-c", help="Directory containing the version to test"),
    setup: str = typer.Option(..., "--setup", help="Shell command run before every measurement (not measured). Use 'true' for none"),
    cmd: str = typer.Option(..., "--cmd", help="Shell command to measure, e.g. 'python bench.py'. Chaining (a && b, pipes, ;) is rejected: put multi-step workloads in one script"),
    iterations: int = typer.Option(30, "--iterations", "-n", min=2, help="Runs per version (30+ recommended)"),
    carbon_intensity: float = typer.Option(475.0, "--intensity", min=0.0, help="Carbon intensity in gCO2e/kWh"),
    output: Path = typer.Option(Path("green-bench-results"), "--output", "-o", help="Folder where results are saved"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Seed for the run order (default: random; it is printed so you can reproduce it)"),
    cooldown: float = typer.Option(10.0, "--cooldown", min=0.0, help="Seconds to wait between setup and each measurement"),
    interval: int = typer.Option(500, "--interval", min=1, help="EnergiBridge sampling interval in ms"),
    timeout: Optional[float] = typer.Option(None, "--timeout", min=1.0, help="Abort any single command after this many seconds"),
    keep_raw: bool = typer.Option(False, "--keep-raw", help="Keep each run's raw EnergiBridge CSV in <results>/raw"),
    resume: bool = typer.Option(False, "--resume", help="Continue an interrupted experiment with the same name"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing results folder without asking"),
    no_plots: bool = typer.Option(False, "--no-plots", help="Skip plot generation"),
    version: Optional[bool] = typer.Option(None, "--version", callback=_version_callback, is_eager=True,
                                           help="Show the version and exit"),
):
    """
    Automates energy measurement between two versions of a project.
    """
    _run_compare(
        name=name, base=base, compare=compare, setup=setup, cmd=cmd, iterations=iterations,
        carbon_intensity=carbon_intensity, output=output, seed=seed, cooldown=cooldown,
        interval=interval, timeout=timeout, keep_raw=keep_raw, resume=resume,
        overwrite=overwrite, no_plots=no_plots,
    )


def _run_compare(*, name, base, compare, setup, cmd, iterations, carbon_intensity, output, seed,
                 cooldown, interval, timeout, keep_raw, resume, overwrite, no_plots):
    console.print("━" * 65, style="dim white")
    console.print(f"[bold green]GreenBench Automated Benchmarking Engine v{__version__}[/bold green]")
    console.print("━" * 65, style="dim white")

    results_dir = output / name
    start_time = datetime.now()
    start_perf = time.perf_counter()

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold white", justify="left", width=20)
    grid.add_column(style="white")
    grid.add_row("Project:", escape(name))
    grid.add_row("Setup:", escape(setup))
    grid.add_row("Workload:", escape(cmd))
    grid.add_row("Base:", f"[cyan]{escape(str(base))}[/cyan]")
    grid.add_row("Compare:", f"[green]{escape(str(compare))}[/green]")
    grid.add_row("Iterations:", f"{iterations} per version")
    grid.add_row("Output:", escape(str(results_dir)))
    grid.add_row("Start Time:", start_time.strftime("%Y-%m-%d %H:%M:%S"))
    console.print(grid)
    console.print()

    exit_code = 0
    try:
        _confirm_overwrite(results_dir, resume, overwrite)
        environment = EnvironmentManager(base_path=base, compare_path=compare, output_path=results_dir)
        orchestrator = ExperimentOrchestrator(environment, MeasurementWrapper(), console=console)
        summary = orchestrator.run_benchmarks(
            name=name, base=str(base), compare=str(compare), setup=setup, cmd=cmd,
            iterations=iterations, seed=seed, cooldown=cooldown, interval_ms=interval,
            timeout=timeout, keep_raw=keep_raw, resume=resume,
        )
        if not summary.completed:
            exit_code = 1

        console.print("[bold yellow][3/3][/bold yellow] [bold white]Analytical Data & Statistical Processing...[/bold white]")
        report = AnalysisEngine.compare_results(summary.data_csv_path, grid_intensity=carbon_intensity, console=console)

        plot_dir = None
        if not no_plots and summary.runs_recorded >= 2:
            plot_dir = AnalysisEngine.generate_visuals(summary.data_csv_path.parent)
            if plot_dir is None:
                console.print(
                    "  [yellow]Plots skipped: install them with[/yellow] " + escape("pip install 'green-bench[plots]'")
                )
            else:
                console.print("  • Generating plots... [bold green]Done.[/bold green]")

        console.print(report)
        if plot_dir:
            console.print(f"[magenta]Artifacts stored at: {escape(str(plot_dir))}[/magenta]")
        if not summary.completed:
            console.print("[bold red]The experiment did not finish. The analysis above uses partial data.[/bold red]")
    except BenchmarkError as err:
        console.print(f"\n[bold red]Error:[/bold red] {escape(str(err))}")
        exit_code = 1
    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted.[/bold red] Partial results are kept; continue with --resume.")
        exit_code = 130

    total = time.perf_counter() - start_perf
    console.print("-" * 50)
    console.print(f"Ended at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    console.print(f"Total duration: {int(total // 60):02d}:{int(total % 60):02d} ({total:.1f} s)")
    raise typer.Exit(exit_code)


DEMO_NAME = "nqueens-demo"
DEMO_DIR = Path("green-bench-demo")
DEMO_WORKLOAD = "nqueens.py 13"


def _copy_demo_programs(dest: Path) -> None:
    """Copy the bundled naive/optimized N-Queens programs into `dest` so the user can see and reuse them."""
    source = resources.files("green_bench") / "demo_data" / "nqueens"
    for version in ("naive", "optimized"):
        target = dest / version
        target.mkdir(parents=True, exist_ok=True)
        for item in (source / version).iterdir():
            if item.is_file() and item.name.endswith(".py"):
                (target / item.name).write_bytes(item.read_bytes())


def _format_command(*, name: str, base: Path, compare: Path, setup: str, cmd: str, iterations: int,
                    cooldown: float, output: Path | None = None, seed: int | None = None) -> str:
    """The `green-bench` invocation as a copy-pasteable, multi-line shell command."""
    def fmt(value: float) -> str:
        return f"{value:g}"

    lines = [
        f"green-bench --name {shlex.quote(name)}",
        f"-b {shlex.quote(base.as_posix())} -c {shlex.quote(compare.as_posix())}",
        f"--setup {shlex.quote(setup)} --cmd {shlex.quote(cmd)}",
        f"-n {iterations} --cooldown {fmt(cooldown)}",
    ]
    if output is not None:
        lines[-1] += f" -o {shlex.quote(output.as_posix())}"
    if seed is not None:
        lines[-1] += f" --seed {seed}"
    return " \\\n  ".join(lines)


def _print_command(command: str, title: str) -> None:
    console.print(f"[bold cyan]{title}[/bold cyan]")
    console.print(Text(command), soft_wrap=True, highlight=False)
    console.print()


@app.command()
def demo(
    iterations: int = typer.Option(5, "--iterations", "-n", min=2, help="Runs per version"),
    cooldown: float = typer.Option(5.0, "--cooldown", min=0.0, help="Seconds to wait between setup and each measurement"),
    output: Path = typer.Option(Path("green-bench-results"), "--output", "-o", help="Folder where results are saved"),
    seed: Optional[int] = typer.Option(None, "--seed", help="Seed for the run order"),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing demo results folder without asking"),
    no_plots: bool = typer.Option(False, "--no-plots", help="Skip plot generation"),
):
    """
    Try GreenBench on a bundled example (naive vs. bitmask N-Queens) and see the exact command it ran.
    """
    _copy_demo_programs(DEMO_DIR)
    python = "python" if sys.platform == "win32" or not shutil.which("python3") else "python3"
    base, compare, setup, cmd = DEMO_DIR / "naive", DEMO_DIR / "optimized", "true", f"{python} {DEMO_WORKLOAD}"
    command = _format_command(
        name=DEMO_NAME, base=base, compare=compare, setup=setup, cmd=cmd, iterations=iterations,
        cooldown=cooldown, output=None if output == Path("green-bench-results") else output, seed=seed,
    )

    console.print(f"Demo programs copied to [bold]{escape(str(DEMO_DIR))}/[/bold] (naive/ and optimized/).")
    _print_command(command, "Running this GreenBench command:")

    try:
        _run_compare(
            name=DEMO_NAME, base=base, compare=compare, setup=setup, cmd=cmd, iterations=iterations,
            carbon_intensity=475.0, output=output, seed=seed, cooldown=cooldown, interval=500,
            timeout=None, keep_raw=False, resume=False, overwrite=overwrite, no_plots=no_plots,
        )
    except typer.Exit:
        console.print()
        _print_command(
            command,
            "To repeat this on your own project, run the same command with -b/-c pointing at your two "
            "directories and --cmd at your workload:",
        )
        raise


if __name__ == "__main__":
    app()
