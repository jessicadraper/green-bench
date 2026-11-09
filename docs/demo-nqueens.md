# Example: naive vs optimized N-Queens

Two directories, same program, different algorithm:

| Directory    | Algorithm                                         |
| ------------ | ------------------------------------------------- |
| `naive/`     | backtracking that builds new tuples at every step |
| `optimized/` | the same search using bitmasks (no allocations)   |

Both print the same answer (`13-queens solutions: 73712`). On a typical laptop the naive one takes ~5 s and the optimized one ~1.2 s.
The question for GreenBench: _does the faster version also use less energy, and by how much?_

The programs ship inside the package (`src/green_bench/demo_data/nqueens/`) so that `pip install green-bench` users can run them without cloning this repo.

## Run it

With EnergiBridge available and (if your OS needs it) an elevated terminal:

```bash
green-bench demo                 # quick: 5 runs per version
green-bench demo -n 30           # full: 30 runs per version (about 20 minutes)
```

`demo` prints the exact `green-bench` command it runs.

An A/A control (the same code against itself, so any "difference" is noise) can also be run from the repository root:

```bash
green-bench --name nqueens-aa \
  --base src/green_bench/demo_data/nqueens/naive --compare src/green_bench/demo_data/nqueens/naive \
  --setup 'true' --cmd 'python3 nqueens.py 13' -n 10 --cooldown 5
```
