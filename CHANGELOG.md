# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- Windows: the EnergiBridge output path was quoted POSIX-style (`'...'`), which `cmd.exe` rejects (error 123). Paths are now quoted for the shell in use.
- Windows: on timeout or Ctrl-C the whole process tree (EnergiBridge and the workload) is now stopped, not just `cmd.exe`.
- Windows: `--cmd` validation no longer treats backslashes in paths as escape characters, and `energibridge` is resolved through `PATHEXT` (e.g. a `.cmd` shim).
- Windows: `green-bench demo` uses a setup command that exists in `cmd.exe`, and prints a copy-pasteable command with Windows quoting.

### Added

- The test suite now runs on Windows (`windows-latest`) in CI, alongside Linux and macOS.

## 0.2.0 - 2026-11-09

First public release. This version reworks the private thesis version (0.1.0) for general use: more robust experiment handling, safer file handling, broader platform support and a revised statistical report.

### Changed

- Run order is block-randomized: each baseline/treatment pair is shuffled, so groups stay balanced and no label repeats more than twice in a row. The seed is printed and can be reused with `--seed`.
- Energy is read from whatever power/energy column EnergiBridge provides instead of one hardcoded name.
- Statistics report medians, a bootstrap 95% CI for the median change, and the probability that a treatment run uses less energy, next to the Mann-Whitney U test. A warning is shown below 10 runs per group.
- Results are written to `<output>/<name>/`; commands, paths and logs are handled as resolved `Path`s and shell-quoted.
- Python 3.10+ is supported (was 3.13+).
- Plotting (`matplotlib`, `seaborn`) is optional: `pip install "green-bench[plots]"`.
- The N-Queens example programs moved from `examples/nqueens/` into the package (`src/green_bench/demo_data/nqueens/`).

### Added

- `--overwrite`, and a prompt when the results folder already exists. Only GreenBench's own files are deleted, and only after pre-flight passes, so a mistyped option can no longer leave a mix of old and new results (stale plots and `results.csv` are cleared at the start of every run, including `--resume`).
- `--seed`, `--cooldown`, `--interval`, `--timeout`, `--keep-raw`, `--resume`, `--no-plots`, `--version`.
- Failed commands stop the experiment cleanly (non-zero exit code, partial results kept, `--resume`).
- stderr is captured in `output.log`; Ctrl-C / timeouts stop the whole process group.
- Unit tests and a fake-EnergiBridge CLI test; CI workflows; docs and examples.
- `green-bench demo`: runs a bundled N-Queens comparison (works from a plain `pip install`, no repo clone) and prints the full equivalent `green-bench` command. `green-bench --name ...` remains shorthand for `green-bench compare --name ...`.

### Fixed

- `--cmd` that chains commands (`&&`, `||`, `;`, `|`, `&`, newline) is now rejected up front: previously only the first command was measured, silently. Use a single script instead.
- A failed or unreadable measurement is no longer recorded as `0 J`.
- Stale `data.csv` from an earlier run can no longer be mixed into a new analysis.
- `--output` / `--name` with spaces, and unsafe `--name` values.
- Clearer errors for workloads that finish before two telemetry samples ("covers 0 seconds") and for zero-power data (hints at permissions).
- A failing setup command mid-experiment now also says partial results are kept and `--resume` can continue.

### Removed

- Thermal Throttling Index (and its plot and CSV column).
- Unused dependencies (`gitpython`, `psutil` at runtime).

## [0.1.0] - 2026-08-23

Private version developed for, and used in, the MSc thesis _"Evaluating the Environmental Impact of Software Design: An Empirical Analysis using Automated Software Emissions Benchmarking"_ (Hochschule Campus Wien, 2026). Not published.

- Command-line orchestrator wrapping EnergiBridge to compare a baseline and a treatment directory.
- Warm-up runs, interleaved baseline/treatment iterations (default 30) and a cool-down between iterations.
- Energy in Joules via trapezoidal integration of power over time.
- Two-tailed Mann-Whitney U test (α = 0.05), mean energy and % change, and operational emissions at a configurable grid carbon intensity (default 475 gCO2e/kWh).
- CSV export, boxplot and run-stability plot.
