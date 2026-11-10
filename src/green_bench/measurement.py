"""Thin facade around the external EnergiBridge telemetry tool."""

import os
import shlex
import shutil
import subprocess
from pathlib import Path


class BenchmarkError(Exception):
    """A problem the user can act on (bad setup, failed workload, missing tool)."""


class MeasurementError(BenchmarkError):
    """Telemetry output is missing, malformed, or cannot be interpreted."""


def is_windows() -> bool:
    """Whether commands will be run by ``cmd.exe`` (a seam so tests can exercise both branches)."""
    return os.name == "nt"


def quote_arg(value: object) -> str:
    """Quote one argument for the shell that ``Popen(shell=True)`` uses on this OS.

    POSIX shells understand ``shlex.quote``'s single quotes; ``cmd.exe`` does not,
    so on Windows use the double-quote rules of ``list2cmdline``.
    """
    if is_windows():
        return subprocess.list2cmdline([str(value)])
    return shlex.quote(str(value))


class MeasurementWrapper:
    """Facade abstraction layer for external hardware tools."""

    BINARY = "energibridge"

    @classmethod
    def verify_dependencies(cls) -> None:
        """Check that EnergiBridge is installed and runnable."""
        # which() honours PATHEXT, so .cmd/.bat shims resolve on Windows too.
        resolved = shutil.which(cls.BINARY)
        not_found = BenchmarkError(
            "EnergiBridge was not found on your PATH. Install it from "
            "https://github.com/tdurieux/EnergiBridge and make sure `energibridge` "
            "runs in this terminal (it may need elevated privileges)."
        )
        if resolved is None:
            raise not_found
        try:
            subprocess.run([resolved, "--version"], capture_output=True, check=True)
        except FileNotFoundError:
            raise not_found from None
        except subprocess.CalledProcessError as err:
            raise BenchmarkError(
                f"`energibridge --version` failed with exit code {err.returncode}. "
                "Check that it is installed correctly and that you have the required permissions."
            ) from err

    # Unquoted shell operators that would split the command so that EnergiBridge only wraps the first part.
    _CHAIN_OPERATORS = frozenset({"&&", "||", ";", "|", "&"})

    @classmethod
    def validate_command(cls, target_cmd: str) -> None:
        """Reject ``--cmd`` values that chain several commands.

        EnergiBridge is prepended to the command line, so in ``a && b`` only ``a`` would be
        measured, silently. Operators inside quotes (``sh -c "a && b"``) are not chaining and
        are allowed.
        """
        if not target_cmd.strip():
            raise BenchmarkError("--cmd is empty.")
        if "\n" in target_cmd.strip():
            operator = "a newline"
        else:
            # cmd.exe: backslashes are path separators, not escapes.
            lexer = shlex.shlex(target_cmd, posix=not is_windows(), punctuation_chars=True)
            lexer.whitespace_split = True
            try:
                found = next((t for t in lexer if t in cls._CHAIN_OPERATORS), None)
            except ValueError as err:
                raise BenchmarkError(f"Could not parse --cmd ({err}). Check its quotes.") from err
            if found is None:
                return
            operator = f"'{found}'"
        raise BenchmarkError(
            f"--cmd contains {operator}, which chains several commands, so EnergiBridge would only "
            "measure the first one. Put the whole workload in a single script and pass that, "
            "e.g. --cmd './run_benchmark.sh'."
        )

    @classmethod
    def generate_profile_command(cls, output_csv: Path, target_cmd: str, interval_ms: int = 500) -> str:
        """Build the shell command that runs ``target_cmd`` under EnergiBridge.

        The sampling interval defaults to 500 ms: very short intervals can make
        EnergiBridge compete with the workload for CPU and sample late.
        ``target_cmd`` is passed through verbatim (it is user-supplied shell text);
        only the output path is quoted, using the quoting rules of the platform's shell.
        """
        return f"{cls.BINARY} -i {int(interval_ms)} --output {quote_arg(output_csv)} {target_cmd}"

    @classmethod
    def generate_warmup_command(cls, output_csv: Path, target_cmd: str, interval_ms: int = 500) -> str:
        """Warm-up runs use exactly the same command path as measured runs."""
        return cls.generate_profile_command(output_csv, target_cmd, interval_ms)
