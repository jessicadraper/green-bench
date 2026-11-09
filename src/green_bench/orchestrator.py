"""Schedules, executes and records the benchmark runs."""

import csv
import json
import random
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.markup import escape

from green_bench.analysis import AnalysisEngine
from green_bench.environment import EnvironmentManager, WorkloadExecutionError
from green_bench.measurement import BenchmarkError, MeasurementWrapper
from green_bench.results import clear_derived, clear_results

DATA_FIELDS = [
    "run_id", "label", "branch_path", "command",
    "energy_joules", "energy_kwh", "duration_sec", "timestamp",
]


@dataclass
class RunSummary:
    data_csv_path: Path
    completed: bool  # False if the experiment stopped early (workload failure)
    seed: int
    runs_recorded: int


def build_plan(base: str, compare: str, iterations: int, seed: int) -> list[tuple[str, str]]:
    """Block-randomized interleaving.

    Each block holds one baseline and one treatment run in random order. Groups stay
    perfectly balanced, no label can repeat more than twice in a row, and the order is
    still random (so slow drifts such as heat build-up cannot favour one group).
    """
    rng = random.Random(seed)
    plan: list[tuple[str, str]] = []
    for _ in range(iterations):
        block = [(base, "baseline"), (compare, "treatment")]
        rng.shuffle(block)
        plan.extend(block)
    return plan


class ExperimentOrchestrator:
    """Central class handling scheduling, randomized interleaving, and data recording."""

    def __init__(self, environment: EnvironmentManager, measurement: MeasurementWrapper,
                 console: Optional[Console] = None):
        self.environment = environment
        self.measurement = measurement
        self.console = console or Console()

    # ------------------------------------------------------------------ steps
    def pre_flight_check(self) -> None:
        c = self.console
        c.print("[bold yellow][1/3][/bold yellow] [bold white]Pre-Flight & Environmental Checks...[/bold white]")
        with c.status("• Validating directories and dependencies...", spinner="dots"):
            warnings = self.environment.validate_environments()
            self.measurement.verify_dependencies()
        for w in warnings:
            c.print(f"  [yellow]! {w}[/yellow]")
        c.print("  • Validating directories and dependencies... [bold green]Success.[/bold green]")

    def run_warmup(self, target_path: str, setup: str, cmd: str, results_dir: Path,
                   interval_ms: int, timeout: Optional[float]) -> None:
        """Run setup + the measured command once (through the same code path) and discard it."""
        c = self.console
        warm_csv = results_dir / "warmup.csv"
        with c.status(f"• Warming up [yellow]{target_path}[/yellow]...", spinner="dots"):
            self.environment.set_active_target(target_path)
            self.environment.execute_workload(setup, run_context="WARMUP-SETUP", timeout=timeout)
            time.sleep(1)
            profile = self.measurement.generate_warmup_command(warm_csv, cmd, interval_ms)
            self.environment.execute_workload(profile, run_context="WARMUP", timeout=timeout)
        warm_csv.unlink(missing_ok=True)
        c.print(f"  • Warming up {target_path}... [bold green]Done.[/bold green]")

    @staticmethod
    def save_to_results(path: Path, data_dict: dict) -> None:
        write_header = not path.exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=DATA_FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerow(data_dict)

    # ------------------------------------------------------------- bookkeeping
    @staticmethod
    def _completed_run_ids(data_csv: Path) -> set[int]:
        if not data_csv.exists():
            return set()
        with open(data_csv, newline="", encoding="utf-8") as f:
            return {int(row["run_id"]) for row in csv.DictReader(f)}

    def _load_or_create_plan(self, results_dir: Path, base: str, compare: str, cmd: str,
                             iterations: int, seed: Optional[int], resume: bool):
        plan_file = results_dir / "plan.json"
        if resume:
            if not plan_file.exists():
                raise BenchmarkError(f"Cannot resume: no previous experiment found in {results_dir}")
            saved = json.loads(plan_file.read_text(encoding="utf-8"))
            same = (saved["base"], saved["compare"], saved["cmd"], saved["iterations"]) == (
                base, compare, cmd, iterations)
            if not same:
                raise BenchmarkError(
                    "Cannot resume: --base/--compare/--cmd/--iterations differ from the original experiment.")
            return [tuple(p) for p in saved["plan"]], saved["seed"]

        seed = random.SystemRandom().randrange(2**31) if seed is None else seed
        plan = build_plan(base, compare, iterations, seed)
        plan_file.write_text(json.dumps({
            "base": base, "compare": compare, "cmd": cmd, "iterations": iterations,
            "seed": seed, "plan": plan,
        }, indent=2), encoding="utf-8")
        return plan, seed

    # --------------------------------------------------------------- the loop
    def run_benchmarks(self, name: str, base: str, compare: str, setup: str, cmd: str,
                       iterations: int, seed: Optional[int] = None, cooldown: float = 10.0,
                       interval_ms: int = 500, timeout: Optional[float] = None,
                       keep_raw: bool = False, resume: bool = False) -> RunSummary:
        c = self.console
        results_dir = self.environment.output_path
        data_csv_path = results_dir / "data.csv"

        self.measurement.validate_command(cmd)
        self.pre_flight_check()
        # Only after pre-flight passed: a mistyped option must not destroy earlier results.
        # (The CLI has already asked the user for consent.)
        if resume:
            clear_derived(results_dir)  # stale plots/summary must not outlive an early failure
        else:
            clear_results(results_dir)  # never mix in anything from an older run
        plan, seed = self._load_or_create_plan(results_dir, base, compare, cmd, iterations, seed, resume)
        done = self._completed_run_ids(data_csv_path) if resume else set()
        self.environment.initialize_log(append=resume)
        c.print(f"  • Run order seed: [bold]{seed}[/bold] (reuse with --seed {seed} to reproduce)")
        if resume:
            c.print(f"  • Resuming: {len(done)}/{len(plan)} runs already recorded.")

        try:
            self.run_warmup(base, setup, cmd, results_dir, interval_ms, timeout)
            self.run_warmup(compare, setup, cmd, results_dir, interval_ms, timeout)
        except WorkloadExecutionError as err:
            raise BenchmarkError(self._describe_failure("Warm-up failed", err)) from err

        c.print("[bold yellow][2/3][/bold yellow] [bold white]Executing Experiment Runs...[/bold white]")
        completed = True
        recorded = len(done)
        raw_dir = results_dir / "raw"
        if keep_raw:
            raw_dir.mkdir(exist_ok=True)

        with c.status("[bold green]Starting runs...") as status:
            for i, (path, label) in enumerate(plan):
                run_id = i + 1
                if run_id in done:
                    continue
                prefix = f"Iteration {run_id}/{len(plan)} | {label} ({path})"

                self.environment.set_active_target(path)
                status.update(f"{prefix} | [yellow]setup...[/yellow]")
                try:
                    self.environment.execute_workload(setup, run_context="SETUP", timeout=timeout)
                except WorkloadExecutionError as err:
                    c.print(f"[bold yellow]{escape(self._describe_failure('Setup failed', err))}[/bold yellow]")
                    c.print("[bold yellow]Stopping early; partial results are kept "
                            "(continue later with --resume).[/bold yellow]")
                    completed = False
                    break

                status.update(f"{prefix} | [yellow]cooling down ({cooldown:g}s)...[/yellow]")
                time.sleep(cooldown)

                output_csv = results_dir / f"run_{run_id}_{label}.csv"
                profile_cmd = self.measurement.generate_profile_command(output_csv, cmd, interval_ms)
                status.update(f"{prefix} | [yellow]measuring...[/yellow]")
                try:
                    self.environment.execute_workload(profile_cmd, timeout=timeout)
                except WorkloadExecutionError as err:
                    output_csv.unlink(missing_ok=True)
                    failure = self._describe_failure(f"Workload failed on run {run_id}", err)
                    c.print(f"[bold yellow]{escape(failure)}[/bold yellow]")
                    c.print("[bold yellow]Stopping early; partial results are kept "
                            "(continue later with --resume).[/bold yellow]")
                    completed = False
                    break

                try:
                    joules, duration = AnalysisEngine.calculate_eb_joules(output_csv)
                except BenchmarkError as err:
                    raise BenchmarkError(f"Run {run_id} produced unusable telemetry: {err}") from err

                if keep_raw:
                    shutil.move(str(output_csv), str(raw_dir / output_csv.name))
                else:
                    output_csv.unlink(missing_ok=True)

                self.save_to_results(data_csv_path, {
                    "run_id": run_id,
                    "label": label,
                    "branch_path": path,
                    "command": cmd,
                    "energy_joules": joules,
                    "energy_kwh": AnalysisEngine.calculate_kwh(joules),
                    "duration_sec": duration,
                    "timestamp": datetime.now().isoformat(),
                })
                recorded += 1
                c.print(f"  ✓ {prefix} | [bold green]Done.[/bold green] ({joules:,.1f} J, {duration:.1f} s)")

        return RunSummary(data_csv_path, completed, seed, recorded)

    @staticmethod
    def _describe_failure(headline: str, err: WorkloadExecutionError) -> str:
        msg = f"{headline}: {err}"
        if err.tail:
            msg += "\n  Last output:\n    " + err.tail.replace("\n", "\n    ")
        return msg
