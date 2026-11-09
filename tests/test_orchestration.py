import csv
import shlex
import sys

import pytest

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
    parts = shlex.split(cmd)
    assert parts[:3] == ["energibridge", "-i", "250"]
    assert parts[4] == str(out)
    assert parts[5:] == ["python", "bench.py"]


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
    env.execute_workload("pwd; echo oops 1>&2")
    log = env.log_path.read_text()
    assert str(b.resolve()) in log and "oops" in log  # stderr is captured too


def test_execute_workload_failure_and_timeout(tmp_path):
    env, a, _ = _env(tmp_path)
    env.initialize_log()
    with pytest.raises(WorkloadExecutionError) as exc:
        env.execute_workload("echo boom; exit 3")
    assert exc.value.return_code == 3 and "boom" in exc.value.tail
    with pytest.raises(WorkloadExecutionError, match="timed out"):
        env.execute_workload(f"{shlex.quote(sys.executable)} -c 'import time; time.sleep(30)'", timeout=1)


def test_set_active_target_rejects_unknown_dir(tmp_path):
    env, _, _ = _env(tmp_path)
    with pytest.raises(ValueError):
        env.set_active_target(tmp_path)


def _orchestrator(tmp_path):
    env, a, b = _env(tmp_path)
    return ExperimentOrchestrator(env, MeasurementWrapper()), env, a, b


def test_full_run_with_fake_energibridge(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    summary = orch.run_benchmarks("t", str(a), str(b), "true", "true", iterations=3, seed=1, cooldown=0)
    assert summary.completed and summary.runs_recorded == 6
    rows = list(csv.DictReader(open(summary.data_csv_path)))
    assert len(rows) == 6 and {r["label"] for r in rows} == {"baseline", "treatment"}
    assert all(float(r["energy_joules"]) > 0 for r in rows)
    assert not list(env.output_path.glob("run_*.csv"))  # raw files cleaned up


def test_warmup_failure_is_a_clean_error_and_rerun_works(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    flag = tmp_path / "fail-flag"
    flag.write_text("x")
    cmd = f"test ! -e {shlex.quote(str(flag))}"  # fails while the flag file exists
    with pytest.raises(BenchmarkError, match="Warm-up failed"):
        orch.run_benchmarks("t", str(a), str(b), "true", cmd, iterations=2, seed=1, cooldown=0)
    flag.unlink()
    summary = orch.run_benchmarks("t", str(a), str(b), "true", cmd, iterations=2, seed=1, cooldown=0)
    assert summary.completed and summary.runs_recorded == 4


def test_resume_skips_completed_runs(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    first = orch.run_benchmarks("t", str(a), str(b), "true", "true", iterations=2, seed=5, cooldown=0)
    # simulate a crash after two runs by truncating data.csv
    lines = first.data_csv_path.read_text().splitlines()
    first.data_csv_path.write_text("\n".join(lines[:3]) + "\n")
    resumed = orch.run_benchmarks("t", str(a), str(b), "true", "true", iterations=2, seed=None,
                                  cooldown=0, resume=True)
    assert resumed.seed == 5 and resumed.runs_recorded == 4
    assert len(list(csv.DictReader(open(resumed.data_csv_path)))) == 4


def test_resume_rejects_changed_parameters(tmp_path, fake_energibridge):
    orch, env, a, b = _orchestrator(tmp_path)
    orch.run_benchmarks("t", str(a), str(b), "true", "true", iterations=2, seed=5, cooldown=0)
    with pytest.raises(BenchmarkError, match="Cannot resume"):
        orch.run_benchmarks("t", str(a), str(b), "true", "false", iterations=2, cooldown=0, resume=True)
