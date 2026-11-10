import os
import stat
import sys
from pathlib import Path

import pytest

FAKE_ENERGIBRIDGE = '''#!{python}
"""Minimal stand-in for EnergiBridge: runs the command, writes a plausible CSV."""
import os, shlex, subprocess, sys, time
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("energibridge 0.0-fake"); sys.exit(0)
out = None
rest = []
i = 0
while i < len(args):
    if args[i] in ("-i", "--interval"):
        i += 2
    elif args[i] in ("-o", "--output"):
        out = args[i + 1]; i += 2
    else:
        rest = args[i:]; break
# The shell already split the command into args; re-quote them so spaces/quotes survive.
cmd = subprocess.list2cmdline(rest) if os.name == "nt" else shlex.join(rest)
rc = subprocess.run(cmd, shell=True).returncode
if out:
    with open(out, "w") as f:
        f.write("Delta,Time,SYSTEM_POWER (Watts)\\n")
        for n in range(6):
            f.write(f"500,{{1000 + n * 500}},{{10 + n % 2}}\\n")
sys.exit(rc)
'''


@pytest.fixture
def fake_energibridge(tmp_path, monkeypatch) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = FAKE_ENERGIBRIDGE.format(python=sys.executable)
    if os.name == "nt":
        # No shebangs on Windows: a .cmd shim (found via PATHEXT) calls the Python script.
        (bindir / "energibridge_impl.py").write_text(script)
        exe = bindir / "energibridge.cmd"
        exe.write_text(f'@"{sys.executable}" "%~dp0energibridge_impl.py" %*\r\n')
    else:
        exe = bindir / "energibridge"
        exe.write_text(script)
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return exe


@pytest.fixture
def power_csv(tmp_path) -> Path:
    """Constant 10 W for 5 seconds -> exactly 50 J."""
    path = tmp_path / "run.csv"
    rows = ["Delta,Time,SYSTEM_POWER (Watts)"] + [f"1000,{1000 + n * 1000},10" for n in range(6)]
    path.write_text("\n".join(rows) + "\n")
    return path
