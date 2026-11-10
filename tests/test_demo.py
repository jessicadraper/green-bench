import os
import shlex

from helpers import PASS
from typer.testing import CliRunner

from green_bench.__main__ import _format_command, app
from green_bench.measurement import quote_arg

runner = CliRunner()


def _printed_command(output: str) -> list[str]:
    """Extract the first printed `green-bench ...` command (joined across continuation lines)."""
    lines = output.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("green-bench "))
    parts = []
    for line in lines[start:]:
        parts.append(line.rstrip("\\").strip() if line.rstrip().endswith("\\") else line.strip())
        if not line.rstrip().endswith("\\"):
            break
    return shlex.split(" ".join(parts))[1:]


def test_demo_runs_and_prints_the_command(tmp_path, monkeypatch, fake_energibridge):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["demo", "-n", "2", "--cooldown", "0", "--no-plots", "--seed", "1"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "green-bench-demo" / "naive" / "nqueens.py").exists()
    assert (tmp_path / "green-bench-demo" / "optimized" / "nqueens.py").exists()
    assert (tmp_path / "green-bench-results" / "nqueens-demo" / "results.csv").exists()
    for token in ("--name nqueens-demo", "-b green-bench-demo/naive", "-c green-bench-demo/optimized",
                  "-n 2", "--cooldown 0"):
        assert token in result.output.replace("\\\n", "").replace("  ", " ")
    expected_setup = ' -c "pass"' if os.name == "nt" else "--setup true"
    assert expected_setup in result.output.replace("\\\n", "").replace("\\\"", '"')
    assert result.output.count("--name nqueens-demo") >= 2  # shown before and after the run


def test_printed_command_is_copy_pasteable(tmp_path, monkeypatch, fake_energibridge):
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["demo", "-n", "2", "--cooldown", "0", "--no-plots", "--seed", "1"])
    args = _printed_command(first.output)
    assert "--name" in args and "-b" in args and "-c" in args and "--cmd" in args
    again = runner.invoke(app, args + ["--no-plots", "--overwrite"])
    assert again.exit_code == 0, again.output


def test_demo_without_energibridge_is_a_clean_error_but_still_shows_the_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    result = runner.invoke(app, ["demo", "-n", "2", "--cooldown", "0"])
    assert result.exit_code == 1
    assert "EnergiBridge was not found" in result.output
    assert "--name nqueens-demo" in result.output
    assert "Traceback" not in result.output


def test_both_invocation_styles_work(tmp_path, fake_energibridge):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    base = ["--name", "x", "-b", str(a), "-c", str(b), "--setup", PASS, "--cmd", PASS, "-n", "2",
            "--cooldown", "0", "--no-plots", "-o", str(tmp_path / "out")]
    assert runner.invoke(app, base).exit_code == 0
    assert runner.invoke(app, ["compare", *base, "--overwrite"]).exit_code == 0


def test_help_lists_demo():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0 and "demo" in result.output


def test_format_command_quotes_and_includes_optional_flags():
    from pathlib import Path

    text = _format_command(name="n", base=Path("a b"), compare=Path("c"), setup="true", cmd="python3 x.py 1",
                           iterations=3, cooldown=2.5, output=Path("out"), seed=7)
    assert f"-b {quote_arg('a b')}" in text and f"--cmd {quote_arg('python3 x.py 1')}" in text
    assert "-n 3 --cooldown 2.5 -o out --seed 7" in text
