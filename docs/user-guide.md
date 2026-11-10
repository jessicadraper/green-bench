# User Guide

Green Bench is intended to be an easy-to-use Python CLI tool for running energy experiments within a developer's local workflow.

## Installing

```bash
pip install green-bench               # core
pip install "green-bench[plots]"      # + matplotlib/seaborn for charts
```

GreenBench shells out to **EnergiBridge**, which must be installed separately and be runnable as `energibridge` from your terminal. It reads hardware energy counters; on macOS and Linux this typically needs an elevated (root) terminal. Check with:

```bash
energibridge --version
```

**Windows:** run GreenBench from an elevated (administrator) terminal. Commands are run by `cmd.exe`, so quote with double quotes (single quotes are not quote characters there).

If it is missing GreenBench stops immediately with an explanation instead of failing mid-experiment.

## Try it first: `green-bench demo`

```bash
green-bench demo                 # 5 runs per version, 5 s cooldown
green-bench demo -n 10 --cooldown 10 --seed 1
```

The demo copies a naive and a bitmask N-Queens program into `./green-bench-demo/{naive,optimized}`, prints the exact `green-bench --name ... -b ... -c ... --setup ... --cmd ... -n ... --cooldown ...` command, runs it, and prints the command again afterwards. Replace `-b`/`-c` with your own two directories and `--cmd` with your workload to run the same experiment on your project. Options: `-n`, `--cooldown`, `-o`, `--seed`, `--overwrite`, `--no-plots`.

## Preparing the two versions

GreenBench compares **two directories**. It never switches Git branches itself, so you stay in control of what is in each directory:

```bash
git worktree add ../myproj-base main
git worktree add ../myproj-treatment my-optimization
```

(Two plain `git clone`s work just as well.) Install any dependencies in each directory before you start; the measured command runs _inside_ the directory.

## Choosing the commands

- `--cmd` is the workload. Make it deterministic, run for several seconds, and involve the code you changed. Example: `--cmd 'python3 workload.py'`.
- `--setup` runs _before every measured run_ and is not measured. Use it to reset state (empty a database, delete caches) so every run starts the same. Pass `--setup true` if you need nothing (on Windows, `--setup "echo ready"`).
- Both are shell commands run in the directory being tested.
- `--cmd` must be a **single command**. Chaining (`a && b`, `a; b`, pipes, `&`) is rejected with an error, because EnergiBridge only wraps the first program and the rest would silently go unmeasured. Put multi-step workloads in one script (`--cmd './run_benchmark.sh'`).

## Typical sessions

_Example from a Node.js backend application using TypeScript_

Smoke test (not a real result):

```bash
green-bench --name smoke -b ../base -c ../treat --setup true --cmd 'pnpm tsx workload.ts' -n 3 --cooldown 2
```

Real experiment:

```bash
green-bench --name db-optimization-v1 -b ../base -c ../treat --setup 'pnpm tsx reset.ts' --cmd 'pnpm tsx workload.ts' -n 30 --cooldown 40
```

Noise check (A/A): point `--base` and `--compare` at the same directory (a warning is shown). If the A/A test says "significant", your environment is too noisy to trust smaller effects.

Running a name/folder that already has results asks `Delete these previous results and start over? [y/N]` (default: no). Answer `y`, or pass `--overwrite` in scripts and CI, to replace them. Only files GreenBench wrote are deleted, and only after the pre-flight checks pass. An empty folder is reused silently, and a folder that does not look like a GreenBench results folder is refused. Without a terminal and without `--overwrite` or `--resume` the run stops with an error instead of waiting for input.

Interrupted? Re-run the **same command** with `--resume`. Finished runs are kept and the run order is reloaded from `plan.json`.

## Output files

All in `<output>/<name>/` (default `green-bench-results/<name>/`):

| File                                              | Contents                                                         |
| ------------------------------------------------- | ---------------------------------------------------------------- |
| `data.csv`                                        | One row per measured run (schema below)                          |
| `results.csv`                                     | Summary statistics, one `metric,value` row each                  |
| `energy_distribution.png`, `energy_stability.png` | Charts (need the `plots` extra when installing)                  |
| `output.log`                                      | Everything the commands printed (stdout and stderr)              |
| `plan.json`                                       | Seed and run order (used by `--resume`; reproduce with `--seed`) |
| `raw/`                                            | Raw EnergiBridge CSV per run, only with `--keep-raw`             |

### `data.csv` columns:

- `run_id`
- `label` (`baseline`/`treatment`) -`branch_path`,
- `command`
- `energy_joules`
- `energy_kwh`
- `duration_sec`
- `timestamp`

### `results.csv` metrics:

- group sizes
- mean and median energy per group
- % change of mean and median
- 95% bootstrap CI of the median change
- `prob_treatment_lower`
- grid intensity
- `delta_gco2e_execution` (per execution)
- Mann-Whitney `U` and `p_value`
- `is_statistically_significant`

## Exit codes

`0` success · `1` error or incomplete experiment (partial results are kept and analysed) · `130` interrupted with Ctrl-C.

## Troubleshooting

| Symptom                                    | Likely cause / fix                                                                                                                   |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| "EnergiBridge was not found"               | Install it; make sure `energibridge --version` works in the same terminal                                                            |
| EnergiBridge fails with a permission error | Run the terminal with elevated privileges                                                                                            |
| "No known power or energy column"          | Your EnergiBridge build emits columns GreenBench doesn't know; the message lists the ones found. Please open an issue with that list |
| "has 1 sample(s); need at least 2"         | Workload shorter than the sampling interval: lengthen the workload or lower `--interval`                                             |
| Workload fails                             | The last output lines are printed; full output is in `output.log`                                                                    |
| "Plots skipped"                            | `pip install "green-bench[plots]"`                                                                                                   |
| Wildly varying runs                        | Close other apps, plug in power, disable sleep, check the stability chart for a drift, run an A/A test                               |
