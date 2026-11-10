"""Runs shell commands inside the two project directories being compared."""

import os
import re
import signal
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Optional, Union

from green_bench.measurement import BenchmarkError

# EnergiBridge may echo telemetry rows to stdout: only digits, signs, dots, 'e', commas, spaces.
_TELEMETRY_ROW = re.compile(r"^[\d.,+\-eE\s]+$")


class WorkloadExecutionError(BenchmarkError):
    """Raised when a workload subprocess fails (non-zero exit code or timeout)."""

    def __init__(self, return_code: int, message: str, tail: str = ""):
        self.return_code = return_code
        self.tail = tail
        super().__init__(message)


def _is_telemetry_row(line: str) -> bool:
    return line.count(",") > 5 and bool(_TELEMETRY_ROW.match(line))


class EnvironmentManager:
    """Manages and routes command execution across two pre-configured directories."""

    def __init__(self, base_path: Union[str, Path], compare_path: Union[str, Path], output_path: Union[str, Path]):
        self.base_path = Path(base_path).resolve()
        self.compare_path = Path(compare_path).resolve()

        # Directory the next command will run in (switched during the experiment loop)
        self.active_path: Path = self.base_path

        self.output_path = Path(output_path).resolve()
        self.output_path.mkdir(exist_ok=True, parents=True)
        self.log_path = self.output_path / "output.log"

    def initialize_log(self, append: bool = False) -> None:
        """Start a fresh log (or keep appending when resuming)."""
        if append and self.log_path.exists():
            return
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write("=" * 67 + "\n")
            f.write("GREENBENCH SESSION RUN LOG\n")
            f.write("=" * 67 + "\n")

    def validate_environments(self) -> list[str]:
        """Check both directories exist and differ. Returns a list of non-fatal warnings."""
        warnings: list[str] = []
        for label, path in (("Base", self.base_path), ("Compare", self.compare_path)):
            if not path.is_dir():
                raise BenchmarkError(f"{label} path does not exist or is not a directory: {path}")
        if self.base_path == self.compare_path:
            warnings.append(
                "Base and compare point to the same directory; the experiment will compare a "
                "project with itself (useful as an A/A noise check, not for comparing versions)."
            )
        return warnings

    def set_active_target(self, target: Union[str, Path]) -> None:
        """Select the directory (base or compare) that subsequent commands run in."""
        resolved = Path(target).resolve()
        if resolved not in (self.base_path, self.compare_path):
            raise ValueError(f"Unknown target: {target}")
        self.active_path = resolved

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        """Stop the process and everything it spawned (EnergiBridge + workload)."""
        if os.name == "nt":
            # terminate() would only stop cmd.exe; /T takes the whole tree down with it.
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, PermissionError):
            pass
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)

    def execute_workload(
        self, command: str, run_context: str = "WORKLOAD", timeout: Optional[float] = None
    ) -> int:
        """Run ``command`` (shell syntax) in the active directory and log its output.

        stdout and stderr are both written to ``output.log``. Raises
        WorkloadExecutionError on a non-zero exit code or when ``timeout`` expires.
        """
        with open(self.log_path, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n{'=' * 80}\n")
            log_file.write(f"[GreenBench] Target: {self.active_path} | Phase: {run_context}\n")
            log_file.write(f"[GreenBench] Executing: {command}\n")
            log_file.write(f"{'=' * 80}\n\n")
            log_file.flush()

            # Own process group / session so we can stop the whole tree.
            if os.name == "nt":
                group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            else:
                group = {"start_new_session": True}
            try:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    cwd=self.active_path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    **group,
                )
            except OSError as err:
                raise WorkloadExecutionError(-1, f"Could not start command '{command}': {err}") from err

            timed_out = threading.Event()
            timer = None
            if timeout:
                def _on_timeout():
                    timed_out.set()
                    self._terminate(process)

                timer = threading.Timer(timeout, _on_timeout)
                timer.start()

            tail: deque[str] = deque(maxlen=15)
            try:
                for line in process.stdout:
                    stripped = line.strip()
                    if stripped and _is_telemetry_row(stripped):
                        continue
                    log_file.write(line)
                    log_file.flush()
                    if stripped:
                        tail.append(stripped)
                return_code = process.wait()
            except KeyboardInterrupt:
                self._terminate(process)
                log_file.write("\nInterrupted by user.\n")
                raise
            finally:
                if timer:
                    timer.cancel()

            if timed_out.is_set():
                log_file.write(f"\nTimed out after {timeout}s\n")
                raise WorkloadExecutionError(
                    return_code, f"Command timed out after {timeout}s: {command}", "\n".join(tail)
                )
            if return_code != 0:
                log_file.write(f"\nSubprocess failed with exit code {return_code}\n")
                raise WorkloadExecutionError(
                    return_code,
                    f"Command failed with exit code {return_code}: {command}",
                    "\n".join(tail),
                )
            return return_code
