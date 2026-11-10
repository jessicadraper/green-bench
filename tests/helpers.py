"""Shell-portable workload commands for tests (``true``/``sh``/``pwd`` do not exist in cmd.exe)."""

import sys

from green_bench.measurement import quote_arg


def py(code: str) -> str:
    """A shell command that runs ``code`` with the current Python, quoted for this platform's shell."""
    return f"{quote_arg(sys.executable)} -c {quote_arg(code)}"


PASS = py("pass")
FAIL = py("import sys; sys.exit(1)")
