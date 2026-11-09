"""Energy integration, carbon conversion, statistics and (optional) plots."""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from scipy.stats import mannwhitneyu

from green_bench.measurement import MeasurementError

JOULES_PER_KWH = 3.6e6
ALPHA = 0.05
MIN_RECOMMENDED_N = 10

# Energy sources in order of preference. EnergiBridge exposes different columns per
# platform, so we inspect the header instead of assuming one name.
#   power columns   -> integrated over time (trapezoidal rule)
#   energy columns  -> cumulative counters (last sample minus first sample)
POWER_COLUMNS = ["SYSTEM_POWER (Watts)"]
ENERGY_COLUMNS = ["PACKAGE_ENERGY (J)", "CPU_ENERGY (J)"]
TIME_COLUMN = "Time"  # milliseconds


class AnalysisEngine:
    """Data processing, numerical integration, significance testing, carbon maths and plots."""

    # ------------------------------------------------------------------ energy
    @staticmethod
    def _pick_column(columns, exact: list[str], suffix: str) -> Optional[str]:
        for name in exact:
            if name in columns:
                return name
        # Fallback: first column that looks like the right kind of metric, e.g. "FOO_POWER (Watts)".
        for name in columns:
            if name.endswith(suffix):
                return name
        return None

    @classmethod
    def calculate_eb_joules(cls, csv_path: Path) -> tuple[float, float]:
        """Total energy (Joules) and duration (seconds) of one EnergiBridge run.

        Raises MeasurementError (never returns a silent 0) if the file is missing,
        too short, or has no recognisable energy/power column.
        """
        csv_path = Path(csv_path)
        try:
            df = pd.read_csv(csv_path)
        except FileNotFoundError:
            raise MeasurementError(f"Telemetry file not found: {csv_path}") from None
        except Exception as err:
            raise MeasurementError(f"Could not read telemetry file {csv_path.name}: {err}") from err

        if len(df) < 2:
            raise MeasurementError(
                f"{csv_path.name} has {len(df)} sample(s); need at least 2. "
                "The workload may be too short for the sampling interval."
            )
        if TIME_COLUMN not in df.columns:
            raise MeasurementError(f"{csv_path.name} has no '{TIME_COLUMN}' column. Columns: {list(df.columns)}")

        elapsed = (df[TIME_COLUMN] - df[TIME_COLUMN].min()) / 1000.0
        duration = float(elapsed.max())
        if duration <= 0:
            raise MeasurementError(
                f"{csv_path.name} covers 0 seconds: the workload finished before EnergiBridge could take "
                "two samples at different times. Use a workload that runs for several seconds."
            )

        power_col = cls._pick_column(df.columns, POWER_COLUMNS, "(Watts)")
        if power_col is not None:
            joules = float(np.trapezoid(df[power_col], x=elapsed))
        else:
            energy_col = cls._pick_column(df.columns, ENERGY_COLUMNS, "ENERGY (J)")
            if energy_col is None:
                raise MeasurementError(
                    "No known power or energy column found in EnergiBridge output. "
                    f"Columns present: {list(df.columns)}"
                )
            joules = float(df[energy_col].iloc[-1] - df[energy_col].iloc[0])

        if not np.isfinite(joules) or joules <= 0:
            raise MeasurementError(
                f"{csv_path.name} produced an invalid energy value ({joules}). "
                "EnergiBridge may lack permission to read the energy counters (try an elevated terminal), "
                "or the platform reports no usable power data."
            )
        return joules, duration

    @staticmethod
    def calculate_kwh(total_joules: float) -> float:
        """Joules -> kilowatt-hours."""
        return total_joules / JOULES_PER_KWH

    @staticmethod
    def calculate_co2_emissions(kwh: float, grid_intensity: float = 475.0) -> float:
        """Operational emissions in gCO2e for ``kwh`` at ``grid_intensity`` gCO2e/kWh."""
        return kwh * grid_intensity

    # -------------------------------------------------------------- statistics
    @staticmethod
    def _bootstrap_median_change_ci(base: np.ndarray, treat: np.ndarray, n_boot: int = 5000, seed: int = 0):
        """95% percentile-bootstrap CI for the % change in median energy."""
        rng = np.random.default_rng(seed)
        b = rng.choice(base, size=(n_boot, len(base)), replace=True)
        t = rng.choice(treat, size=(n_boot, len(treat)), replace=True)
        mb, mt = np.median(b, axis=1), np.median(t, axis=1)
        changes = (mt - mb) / mb * 100
        return float(np.percentile(changes, 2.5)), float(np.percentile(changes, 97.5))

    @classmethod
    def compare_results(cls, data_csv_path: Path, grid_intensity: float = 475.0, console: Optional[Console] = None):
        """Compare baseline vs treatment and write ``results.csv`` next to the data.

        Returns a rich renderable report, or a plain string if there is too little data.
        """
        console = console or Console()
        data_csv_path = Path(data_csv_path)
        if not data_csv_path.exists():
            return "No results were recorded, so there is nothing to analyse."
        df = pd.read_csv(data_csv_path)

        base = df[df["label"] == "baseline"]["energy_joules"].to_numpy(dtype=float)
        treat = df[df["label"] == "treatment"]["energy_joules"].to_numpy(dtype=float)
        n_base, n_treat = len(base), len(treat)

        if n_base < 2 or n_treat < 2:
            return "Need at least 2 runs per group for statistical analysis."

        u_stat, p_value = mannwhitneyu(base, treat, alternative="two-sided")
        mean_base, mean_treat = float(base.mean()), float(treat.mean())
        med_base, med_treat = float(np.median(base)), float(np.median(treat))
        if mean_base <= 0 or med_base <= 0:
            raise MeasurementError("Baseline energy is not positive; cannot compute relative change.")

        pct_change = (mean_treat - mean_base) / mean_base * 100
        pct_change_median = (med_treat - med_base) / med_base * 100
        ci_low, ci_high = cls._bootstrap_median_change_ci(base, treat)
        # P(a random treatment run uses less energy than a random baseline run), ties count half.
        prob_lower = float(u_stat) / (n_base * n_treat)

        co2_base = cls.calculate_co2_emissions(cls.calculate_kwh(mean_base), grid_intensity)
        co2_treat = cls.calculate_co2_emissions(cls.calculate_kwh(mean_treat), grid_intensity)
        co2_delta = co2_treat - co2_base

        metrics = {
            "baseline_n": n_base,
            "treatment_n": n_treat,
            "baseline_mean_joules": mean_base,
            "treatment_mean_joules": mean_treat,
            "baseline_median_joules": med_base,
            "treatment_median_joules": med_treat,
            "treatment_effect_pct_mean": pct_change,
            "treatment_effect_pct_median": pct_change_median,
            "median_effect_ci95_low_pct": ci_low,
            "median_effect_ci95_high_pct": ci_high,
            "prob_treatment_lower": prob_lower,
            "grid_intensity_gco2e_kwh": grid_intensity,
            "delta_gco2e_execution": co2_delta,
            "mann_whitney_u_stat": float(u_stat),
            "p_value": float(p_value),
            "is_statistically_significant": bool(p_value < ALPHA),
        }
        results_csv_path = data_csv_path.parent / "results.csv"
        pd.DataFrame({"metric": list(metrics), "value": list(metrics.values())}).to_csv(results_csv_path, index=False)
        console.print(f"  • Saved summary CSV to [bold cyan]{results_csv_path}[/bold cyan]")

        return cls.generate_report(metrics)

    @classmethod
    def generate_report(cls, m: dict) -> Panel:
        is_significant = m["p_value"] < ALPHA
        res_color = "green" if is_significant else "yellow"
        res_text = (
            "Statistically significant difference detected (reject null hypothesis)"
            if is_significant
            else "No statistically significant difference detected (fail to reject null hypothesis)"
        )

        table = Table(box=None, padding=(0, 2), show_header=False)
        table.add_column("Metric", style="bold cyan")
        table.add_column("Value", justify="right")

        table.add_row("Baseline N Size", f"{m['baseline_n']}")
        table.add_row("Treatment N Size", f"{m['treatment_n']}")
        table.add_row(
            "Baseline Median Energy",
            f"{m['baseline_median_joules']:,.2f} J [dim](mean {m['baseline_mean_joules']:,.2f} J)[/dim]",
        )
        table.add_row(
            "Treatment Median Energy",
            f"{m['treatment_median_joules']:,.2f} J [dim](mean {m['treatment_mean_joules']:,.2f} J)[/dim]",
        )
        style = "green" if m["treatment_effect_pct_median"] < 0 else "red"
        table.add_row(
            "Treatment Effect (median)",
            f"[{style}]{m['treatment_effect_pct_median']:+.2f}%[/{style}] "
            f"[dim](95% CI {m['median_effect_ci95_low_pct']:+.1f}% to {m['median_effect_ci95_high_pct']:+.1f}%)[/dim]",
        )
        table.add_row("Treatment Effect (mean)", f"{m['treatment_effect_pct_mean']:+.2f}%")
        table.add_row("P(treatment run < baseline run)", f"{m['prob_treatment_lower']:.0%}")
        table.add_row("Grid Intensity Used", f"{m['grid_intensity_gco2e_kwh']:,.2f} gCO2e/kWh")
        co2_style = "green" if m["delta_gco2e_execution"] < 0 else "red"
        table.add_row(
            "Operational Emissions Delta",
            f"[{co2_style}]{m['delta_gco2e_execution']:+.6f} gCO2e/exec[/{co2_style}]",
        )
        table.add_section()
        table.add_row("\n[bold white]Hypothesis Test (Mann-Whitney U)[/bold white]", "")
        table.add_row("  U statistic", f"{m['mann_whitney_u_stat']:,.1f}")
        table.add_row("  p-value", f"{m['p_value']:.5f} [dim](α = {ALPHA})[/dim]")

        parts = [table]
        small_n = min(m["baseline_n"], m["treatment_n"])
        if small_n < MIN_RECOMMENDED_N:
            parts.append(
                Text(
                    f"\n Warning: only {small_n} runs per group; results are unreliable "
                    f"(>= {MIN_RECOMMENDED_N} recommended, 30 for robust conclusions).",
                    style="bold yellow",
                )
            )
        parts.append(
            Text.assemble("\n", (" OUTCOME: ", f"bold {res_color}"), (res_text, "bold white"))
        )
        return Panel(
            Group(*parts),
            title="[bold white]METRIC EVALUATION & STATISTICAL ANALYSIS[/bold white]",
            title_align="left",
            border_style="green" if is_significant else "blue",
            expand=False,
            padding=(1, 3),
        )

    # ------------------------------------------------------------------- plots
    @staticmethod
    def plots_available() -> bool:
        try:
            import matplotlib  # noqa: F401
            import seaborn  # noqa: F401
        except ImportError:
            return False
        return True

    @staticmethod
    def generate_visuals(results_dir: Path) -> Optional[Path]:
        """Write the energy plots. Returns None if the optional plotting extra is missing."""
        if not AnalysisEngine.plots_available():
            return None
        import matplotlib

        matplotlib.use("Agg")  # headless-safe
        import matplotlib.pyplot as plt
        import seaborn as sns

        results_dir = Path(results_dir)
        df = pd.read_csv(results_dir / "data.csv")
        palette = {"baseline": "#007F61", "treatment": "#fb9b60"}
        with sns.axes_style("whitegrid"):
            # Plot 1: distribution per group
            fig, ax = plt.subplots(figsize=(8, 6))
            sns.boxplot(
                x="label", y="energy_joules", data=df, ax=ax, orient="v", palette=palette, hue="label",
                legend=False, width=0.4, boxprops={"edgecolor": "#DDDDDD", "linewidth": 1},
                whiskerprops={"linewidth": 1.5, "alpha": 0.4}, capprops={"linewidth": 1.5, "alpha": 0.4},
                medianprops={"linewidth": 1, "alpha": 0.3},
            )
            sns.stripplot(x="label", y="energy_joules", data=df, ax=ax, color="black", alpha=0.3, size=5, jitter=0.15)
            ax.set_title("Energy Consumption Distribution Across Groups", fontsize=12, fontweight="bold", pad=12)
            ax.set_ylabel("Total Operational Energy (Joules)")
            ax.set_xlabel("Experimental Group")
            fig.savefig(results_dir / "energy_distribution.png", dpi=300)
            plt.close(fig)

            # Plot 2: energy over the course of the experiment
            df_plot = df.copy()
            df_plot["sequence_idx"] = df_plot.groupby("label").cumcount() + 1
            fig, ax = plt.subplots(figsize=(10, 5))
            sns.lineplot(
                x="sequence_idx", y="energy_joules", hue="label", data=df_plot, ax=ax,
                marker="o", markersize=6, linewidth=2, palette=palette,
            )
            ax.set_title("Runtime Operational Stability Over Iterations", fontsize=12, fontweight="bold", pad=12)
            ax.set_ylabel("Total Operational Energy (Joules)")
            ax.set_xlabel("Sequential Iteration Phase (per group)")
            ax.legend(title="Experimental Group", frameon=True)
            sns.despine(ax=ax, trim=True)
            fig.tight_layout()
            fig.savefig(results_dir / "energy_stability.png", dpi=300)
            plt.close(fig)
        return results_dir
