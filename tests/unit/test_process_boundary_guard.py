"""Architecture guard: external process execution goes through one boundary.

E7-S2 R6/R7 require every capability/integration to execute external commands
through the central :class:`SafeProcessRunner` (argv-only, shell=False,
controlled environment) instead of building ``subprocess``/``os.system`` calls
independently.  AC-07 allows explicitly justified exceptions.

This test statically scans the source tree for direct process execution outside
the single security boundary and a small, documented allowlist, so a future
change that reintroduces an ad-hoc ``subprocess.run``/``Popen`` in a capability
fails loudly instead of silently fragmenting the execution policy again.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "ramalio"

# Patterns that indicate a direct, non-boundary process execution.
_FORBIDDEN = re.compile(
    r"\bsubprocess\.(run|Popen|call|check_call|check_output)\b"
    r"|\bos\.system\b"
    r"|\bshell\s*=\s*True\b"
)

# Documented, justified exceptions (relative POSIX paths under src/ramalio):
#
# * security/process.py       -- IS the boundary (defines SafeProcessRunner).
# * git/runner.py             -- the Git execution boundary: the product's core
#                                mechanism with its own argv-only contract and
#                                error mapping (never a capability/integration).
# * core/project.py           -- read-only Git repository discovery
#                                (`rev-parse --show-toplevel`) during config
#                                resolution, before any capability exists.
_ALLOWED = {
    "security/process.py",
    "git/runner.py",
    "core/project.py",
}


def _python_files() -> list[Path]:
    return [p for p in _SRC_ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_no_direct_process_execution_outside_boundary() -> None:
    offenders: list[str] = []
    for path in _python_files():
        rel = path.relative_to(_SRC_ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            # Ignore comments/docstrap references to the pattern.
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if _FORBIDDEN.search(line):
                offenders.append(f"{rel}:{lineno}: {stripped}")

    assert not offenders, (
        "Direct process execution found outside SafeProcessRunner. Route these "
        "through ramalio.security.SafeProcessRunner (CommandSpec) or add "
        "a documented exception to _ALLOWED:\n" + "\n".join(offenders)
    )


def test_allowlist_entries_exist() -> None:
    # Guard against the allowlist drifting from reality (stale exceptions).
    for rel in _ALLOWED:
        assert (_SRC_ROOT / rel).is_file(), f"stale process-boundary exception: {rel}"
