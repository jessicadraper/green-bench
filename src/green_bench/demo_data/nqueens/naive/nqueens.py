"""Count N-Queens solutions: simple backtracking that copies lists (slow on purpose)."""
import sys


def solve(n, row=0, cols=(), diag1=(), diag2=()):
    if row == n:
        return 1
    total = 0
    for col in range(n):
        if col in cols or (row - col) in diag1 or (row + col) in diag2:
            continue
        total += solve(n, row + 1, cols + (col,), diag1 + (row - col,), diag2 + (row + col,))
    return total


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 9
    print(f"{n}-queens solutions: {solve(n)}")
