"""Count N-Queens solutions: same algorithm using bitmasks (no allocations)."""
import sys


def solve(n, cols=0, diag1=0, diag2=0, full=None):
    full = (1 << n) - 1 if full is None else full
    if cols == full:
        return 1
    total = 0
    free = full & ~(cols | diag1 | diag2)
    while free:
        bit = free & -free
        free ^= bit
        total += solve(n, cols | bit, ((diag1 | bit) << 1) & full, (diag2 | bit) >> 1, full)
    return total


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    print(f"{n}-queens solutions: {solve(n)}")
