import pandas as pd
import pytest

from green_bench.analysis import AnalysisEngine
from green_bench.measurement import MeasurementError


def test_joules_from_power_column(power_csv):
    joules, duration = AnalysisEngine.calculate_eb_joules(power_csv)
    assert joules == pytest.approx(50.0)
    assert duration == pytest.approx(5.0)


def test_joules_from_cumulative_energy_column(tmp_path):
    path = tmp_path / "rapl.csv"
    path.write_text("Time,PACKAGE_ENERGY (J)\n0,100\n1000,130\n2000,160\n")
    joules, duration = AnalysisEngine.calculate_eb_joules(path)
    assert joules == pytest.approx(60.0)
    assert duration == pytest.approx(2.0)


def test_unknown_columns_raise_and_list_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Time,FOO\n0,1\n1000,2\n")
    with pytest.raises(MeasurementError, match="FOO"):
        AnalysisEngine.calculate_eb_joules(path)


def test_missing_and_too_short_files_raise(tmp_path):
    with pytest.raises(MeasurementError):
        AnalysisEngine.calculate_eb_joules(tmp_path / "nope.csv")
    short = tmp_path / "short.csv"
    short.write_text("Time,SYSTEM_POWER (Watts)\n0,5\n")
    with pytest.raises(MeasurementError):
        AnalysisEngine.calculate_eb_joules(short)


def test_kwh_and_co2():
    assert AnalysisEngine.calculate_kwh(3.6e6) == pytest.approx(1.0)
    assert AnalysisEngine.calculate_co2_emissions(2.0, 475.0) == pytest.approx(950.0)


def _write_data(tmp_path, base, treat):
    rows = [{"run_id": i, "label": "baseline", "energy_joules": v} for i, v in enumerate(base)]
    rows += [{"run_id": 100 + i, "label": "treatment", "energy_joules": v} for i, v in enumerate(treat)]
    path = tmp_path / "data.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def test_compare_results_detects_clear_difference(tmp_path):
    path = _write_data(tmp_path, [100 + i for i in range(12)], [50 + i for i in range(12)])
    AnalysisEngine.compare_results(path)
    results = pd.read_csv(tmp_path / "results.csv").set_index("metric")["value"]
    assert float(results["p_value"]) < 0.05
    assert float(results["treatment_effect_pct_median"]) < -40
    assert float(results["prob_treatment_lower"]) == pytest.approx(1.0)


def test_compare_results_needs_two_runs_per_group(tmp_path):
    path = _write_data(tmp_path, [1.0], [2.0])
    assert isinstance(AnalysisEngine.compare_results(path), str)


def test_compare_results_without_data_file(tmp_path):
    assert isinstance(AnalysisEngine.compare_results(tmp_path / "data.csv"), str)


def test_plots_are_written_when_available(tmp_path):
    pytest.importorskip("matplotlib")
    pytest.importorskip("seaborn")
    _write_data(tmp_path, [100 + i for i in range(6)], [50 + i for i in range(6)])
    assert AnalysisEngine.generate_visuals(tmp_path) == tmp_path
    assert (tmp_path / "energy_distribution.png").exists()
    assert (tmp_path / "energy_stability.png").exists()


def test_zero_duration_run_has_a_helpful_message(tmp_path):
    path = tmp_path / "instant.csv"
    path.write_text("Delta,Time,SYSTEM_POWER (Watts)\n0,5000,15\n6,5000,15\n")
    with pytest.raises(MeasurementError, match="several seconds"):
        AnalysisEngine.calculate_eb_joules(path)


def test_zero_power_run_mentions_permissions(tmp_path):
    path = tmp_path / "zeros.csv"
    path.write_text("Time,SYSTEM_POWER (Watts)\n0,0\n1000,0\n2000,0\n")
    with pytest.raises(MeasurementError, match="permission"):
        AnalysisEngine.calculate_eb_joules(path)
