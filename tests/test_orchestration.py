import csv
import os
import shlex
from pathlib import PureWindowsPath

import pytest
from helpers import FAIL, PASS, py

from green_bench.environment import EnvironmentManager, WorkloadExecutionError
from green_bench.measurement import BenchmarkError, MeasurementWrapper
from green_bench.orchestrator import ExperimentOrchestrator, build_plan


def test_plan_is_balanced_reproducible_and_bounded():
    plan = build_plan("a", "b", iterations=50, seed=7)
    assert plan == build_plan("a", "b", iterations=50, seed=7)
    assert [label for _, label in plan].count("baseline") == 50
    # blocks of two => no label may occur three times in a row
    labels = [label for _, label in plan]
    assert all(not (labels[i] == labels[i + 1] == labels[i + 2]) for i in range(len(labels) - 2))
    # and the order really is shuffled, not strict ABAB
    assert plan != build_plan("a", "b", iterations=50, seed=8)
    assert any(labels[i] == labels[i + 1] for i in range(len(labels) - 1))


def test_profile_command_quotes_output_path(tmp_path):
    out = tmp_path / "My Results" / "run.csv"
    cmd = MeasurementWrapper.generate_profile_command(out, "python bench.py", 250)
    if os.name == "nt":
        assert cmd == f'energibridge -i 250 --output "{out}" python bench.py'
    else:
        parts = shlex.split(cmd)
        assert parts[:3] == ["energibridge", "-i", "250"]
        assert parts[4] == str(out)
        assert parts[5:] == ["python", "bench.py"]


def test_profile_command_uses_windows_quoting_on_windows(monkeypatch):
    """Regression: shlex.quote's single quotes are literal characters to cmd.exe (error 123)."""
    monkeypatch.setattr("green_bench.measurement.is_windows", lambda: True)
    out = PureWindowsPath(r"C:\Users\me\My Results\run.csv")
    cmd = MeasurementWrapper.generate_profile_command(out, "python bench.py", 250)
    assert cmd == r'energibridge -i 250 --output "C:\Users\me\My Results\run.csv" python bench.py'
    assert "'" not in cmd
    plain = MeasurementWrapper.generate_profile_command(PureWindowsPath(r"C:\out\run.csv"), "x")
    assert "--output C:\\out\\run.csv x" in plain  # no spaces: no quotes needed


def test_profile_command_uses_posix_quoting_elsewhere(monkeypatch):
    monkeypatch.setattr("green_bench.measurement.is_windows", lambda: False)
    cmd = MeasurementWrapper.generate_profile_command(PureWindowsPath("a b/run.csv"), "x")
    assert "--output 'a b" in cmd


def test_validate_command_keeps_windows_backslashes(monkeypatch):
    monkeypatch.setattr("green_bench.measurement.is_windows", lambda: True)
    MeasurementWrapper.validate_command("C:\\tools\\run.exe --out C:\\dir\\")  # POSIX parsing would raise here
    with pytest.raises(BenchmarkError, match="chains"):
        MeasurementWrapper.validate_command(r"C:\tools\run.exe && other")


def test_verify_dependencies_missing(monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(BenchmarkError, match="not found"):
        MeasurementWrapper.verify_dependencies()


def _env(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    return EnvironmentManager(a, b, tmp_path / "out"), a, b


def test_execute_workload_runs_in_active_dir_and_logs(tmp_path):
    env, a, b = _env(tmp_path)
    env.initialize_log()
    env.set_active_target(b)
    env.execute_workload(py("import os, sys; print(os.getcwd()); print('oops', file=sys.stderr)"))
    log = env.log_path.read_text()
    assert str(b.resolve()) in log and "oops" in log  # stderr is captured too


def test_execute_workload_failure_and_timeout(tmp_path):
    env, a, _ = _env(tmp_path)
    env.initialize_log()
    with pytest.raises(WorkloadExecutionError) as exc:
        env.execute_workload(py("import sys; print('boom'); sys.exit(3)"))
    assert exc.value.return_code == 3 and "boom" in exc.value.tail
    with pytest.raises(WorkloadExecutionError, match="timed out"):
        env.execute_workload(py("import time; time.sleep(30)"), timeout=1)


def test_set_active_target_rejects_unknown_dir(tmp_path):
    env, _, _ = _env(tmp_path)
    with pytest.raises(ValueError):
        env.set_active_target(tmp_path)


def _orchestrator(tmp_path):
    env, a, b = _env(tmp_path)
    return ExperimentOrchestrator(env, MeasurementWrapper()), env, a, b


def test_full_run_with_fake_energibridge(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    summary = orch.run_benchmarks("t", str(a), str(b), PASS, PASS, iterations=3, seed=1, cooldown=0)
    assert summary.completed and summary.runs_recorded == 6
    rows = list(csv.DictReader(open(summary.data_csv_path)))
    assert len(rows) == 6 and {r["label"] for r in rows} == {"baseline", "treatment"}
    assert all(float(r["energy_joules"]) > 0 for r in rows)
    assert not list(env.output_path.glob("run_*.csv"))  # raw files cleaned up


def test_warmup_failure_is_a_clean_error_and_rerun_works(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    flag = tmp_path / "fail-flag"
    flag.write_text("x")
    # fails while the flag file exists
    cmd = py(f"import os, sys; sys.exit(int(os.path.exists({str(flag)!r})))")
    with pytest.raises(BenchmarkError, match="Warm-up failed"):
        orch.run_benchmarks("t", str(a), str(b), PASS, cmd, iterations=2, seed=1, cooldown=0)
    flag.unlink()
    summary = orch.run_benchmarks("t", str(a), str(b), PASS, cmd, iterations=2, seed=1, cooldown=0)
    assert summary.completed and summary.runs_recorded == 4


def test_resume_skips_completed_runs(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    first = orch.run_benchmarks("t", str(a), str(b), PASS, PASS, iterations=2, seed=5, cooldown=0)
    # simulate a crash after two runs by truncating data.csv
    lines = first.data_csv_path.read_text().splitlines()
    first.data_csv_path.write_text("\n".join(lines[:3]) + "\n")
    resumed = orch.run_benchmarks("t", str(a), str(b), PASS, PASS, iterations=2, seed=None,
                                  cooldown=0, resume=True)
    assert resumed.seed == 5 and resumed.runs_recorded == 4
    assert len(list(csv.DictReader(open(resumed.data_csv_path)))) == 4


def test_resume_rejects_changed_parameters(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    orch.run_benchmarks("t", str(a), str(b), PASS, PASS, iterations=2, seed=5, cooldown=0)
    with pytest.raises(BenchmarkError, match="Cannot resume"):
        orch.run_benchmarks("t", str(a), str(b), PASS, FAIL, iterations=2, cooldown=0, resume=True)
