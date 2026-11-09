from typer.testing import CliRunner

from green_bench import __version__
from green_bench.__main__ import app

runner = CliRunner()


def _args(tmp_path, **over):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(exist_ok=True), b.mkdir(exist_ok=True)
    args = ["--name", "demo", "-b", str(a), "-c", str(b), "--setup", "true", "--cmd", "true",
            "-n", "3", "--cooldown", "0", "--seed", "1", "-o", str(tmp_path / "out")]
    return args


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0 and __version__ in result.output


def test_rejects_unsafe_name(tmp_path):
    args = _args(tmp_path)
    args[1] = "../escape"
    assert runner.invoke(app, args).exit_code != 0


def test_missing_energibridge_is_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    result = runner.invoke(app, _args(tmp_path))
    assert result.exit_code == 1
    assert "EnergiBridge was not found" in result.output
    assert "Traceback" not in result.output


def test_end_to_end(tmp_path, fake_energibridge):
    result = runner.invoke(app, _args(tmp_path) + ["--no-plots"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "out" / "demo"
    assert (out / "data.csv").exists() and (out / "results.csv").exists()
    assert "thermal" not in (out / "data.csv").read_text().lower()


def test_failing_workload_exits_nonzero(tmp_path, fake_energibridge):
    args = _args(tmp_path)
    args[args.index("--cmd") + 1] = "false"
    result = runner.invoke(app, args)
    assert result.exit_code == 1


def test_missing_plots_extra_prints_the_full_install_hint(tmp_path, fake_energibridge, monkeypatch):
    from green_bench.analysis import AnalysisEngine

    monkeypatch.setattr(AnalysisEngine, "plots_available", staticmethod(lambda: False))
    result = runner.invoke(app, _args(tmp_path))
    assert result.exit_code == 0, result.output
    assert "green-bench[plots]" in result.output  # rich must not swallow the [plots] part


def test_chained_cmd_is_rejected_but_quoted_operators_are_not(tmp_path, fake_energibridge):
    from green_bench.measurement import MeasurementWrapper

    for chained in ("sleep 1 && sleep 4", "make; ./run", "cat in | ./run", "./run &"):
        args = _args(tmp_path)
        args[args.index("--cmd") + 1] = chained
        result = runner.invoke(app, args)
        assert result.exit_code == 1, chained
        assert "single script" in result.output, chained
        assert not (tmp_path / "out" / "demo" / "data.csv").exists()  # nothing was run

    MeasurementWrapper.validate_command('sh -c "a && b"')  # quoted: allowed
    MeasurementWrapper.validate_command("./run.sh 2>&1")  # redirection: allowed


def _stale_results(tmp_path):
    folder = tmp_path / "out" / "demo"
    folder.mkdir(parents=True)
    for name in ("data.csv", "results.csv", "energy_distribution.png", "plan.json"):
        (folder / name).write_text("stale")
    return folder


def test_declining_the_overwrite_prompt_leaves_the_folder_untouched(tmp_path, fake_energibridge, monkeypatch):
    import green_bench.__main__ as cli

    folder = _stale_results(tmp_path)
    monkeypatch.setattr(cli, "_is_interactive", lambda: True)
    result = runner.invoke(app, _args(tmp_path), input="n\n")
    assert result.exit_code == 1
    assert "Delete these previous results" in result.output and "Aborted" in result.output
    assert all((folder / n).read_text() == "stale" for n in ("data.csv", "results.csv", "plan.json"))


def test_overwrite_deletes_only_greenbench_files_and_only_after_preflight(tmp_path, fake_energibridge):
    folder = _stale_results(tmp_path)
    (folder / "notes.txt").write_text("mine")

    bad = _args(tmp_path) + ["--overwrite"]
    bad[bad.index("-b") + 1] = str(tmp_path / "missing")  # pre-flight fails
    assert runner.invoke(app, bad).exit_code == 1
    assert (folder / "results.csv").exists()  # nothing was deleted by the failed attempt

    failing = _args(tmp_path) + ["--overwrite"]
    failing[failing.index("--cmd") + 1] = "false"  # starts, then fails during warm-up
    assert runner.invoke(app, failing).exit_code == 1
    assert not (folder / "results.csv").exists() and not (folder / "energy_distribution.png").exists()
    assert (folder / "notes.txt").read_text() == "mine"  # not ours: left alone


def test_existing_folder_cases_without_a_terminal(tmp_path, fake_energibridge):
    folder = _stale_results(tmp_path)
    result = runner.invoke(app, _args(tmp_path))  # stdin is not a terminal and no --overwrite
    assert result.exit_code == 1 and "--overwrite" in result.output
    assert (folder / "results.csv").read_text() == "stale"

    foreign = tmp_path / "out" / "other"
    foreign.mkdir()
    (foreign / "thesis.docx").write_text("precious")
    args = _args(tmp_path)
    args[args.index("--name") + 1] = "other"
    result = runner.invoke(app, args + ["--overwrite"])
    assert result.exit_code == 1
    assert "does not look like a GreenBench results folder" in " ".join(result.output.split())  # undo wrapping
    assert (foreign / "thesis.docx").exists()

    empty = tmp_path / "out" / "fresh"
    empty.mkdir()
    args[args.index("--name") + 1] = "fresh"
    assert runner.invoke(app, args + ["--no-plots"]).exit_code == 0  # empty folder: reused silently
