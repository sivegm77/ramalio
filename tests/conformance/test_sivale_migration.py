"""SiVale operational migration evidence (E8-S2 R12).

Automated, reproducible evidence that SiVale's day-to-day lifecycle runs through
the canonical `ramalio` CLI end-to-end, including parallel targets, without any
knowledge of internal scripts (AC-01/AC-02/AC-08).  Uses a SiVale-like config
with the `none` runtime + ports so it runs in CI without external tools.
"""

from __future__ import annotations

import os
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.core.result import ExitCode
from ramalio.git.repository import GitRepository

_SIVALE_LIKE = """
[project]
name = "sivale-zurich"
base_branch = "main"

[target]
regex = "^E[0-9]+-S[0-9]+-[a-z0-9]+(-[a-z0-9]+)*$"
example = "E7-S8-convergencia-schema-tests"
case_sensitive = true

[target.normalization]
trim = true
lowercase_slug = true
replace_spaces = "-"
collapse_dashes = true
slug_separator = "-"
preserve_prefix_segments = 2

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "spec/{target}"

[ports]
enabled = true
start = 8100
size = 20

[capabilities.runtime]
driver = "none"
"""


@pytest.fixture
def sivale(tmp_path: Path) -> Path:
    root = tmp_path / "sivale"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c",
        "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c",
        "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    (root / ".ramalio.toml").write_text(_SIVALE_LIKE, encoding="utf-8")
    return root


def _cli(root: Path, *args: str):
    stdout, stderr = StringIO(), StringIO()
    prev = os.getcwd()
    os.chdir(root)
    try:
        code = main(list(args), stdout=stdout, stderr=stderr)
    finally:
        os.chdir(prev)
    return code, stdout.getvalue(), stderr.getvalue()


_A = "E7-S1-alpha"
_B = "E7-S2-bravo"


# --- AC-08: real end-to-end lifecycle evidence -----------------------------


def test_end_to_end_lifecycle(sivale: Path) -> None:
    # doctor recognizes the project (config valid).
    code, out, _ = _cli(sivale, "doctor")
    assert "CONFIG_VALID" in out

    # init
    code, out, err = _cli(sivale, "init", _A)
    assert code == ExitCode.OK, err
    assert "branch: spec/E7-S1-alpha" in out

    # status READY
    code, out, _ = _cli(sivale, "status", _A)
    assert code == ExitCode.OK
    assert "State: READY" in out

    # stop / start
    assert _cli(sivale, "stop", _A)[0] == ExitCode.OK
    assert _cli(sivale, "start", _A)[0] == ExitCode.OK

    # list shows it
    code, out, _ = _cli(sivale, "list")
    assert "E7-S1-alpha" in out

    # destroy
    code, out, _ = _cli(sivale, "destroy", _A)
    assert code == ExitCode.OK
    assert "worktree_removed: true" in out
    assert GitRepository.from_root(sivale).get_worktree_by_path(
        (sivale / ".local-wt" / _A).resolve()
    ) is None


# --- AC-02: multiple simultaneous workspaces -------------------------------


def test_parallel_targets_via_cli(sivale: Path) -> None:
    assert _cli(sivale, "init", _A)[0] == ExitCode.OK
    assert _cli(sivale, "init", _B)[0] == ExitCode.OK
    code, out, _ = _cli(sivale, "list")
    assert "E7-S1-alpha" in out
    assert "E7-S2-bravo" in out
    g = GitRepository.from_root(sivale)
    assert g.branch_exists("spec/E7-S1-alpha")
    assert g.branch_exists("spec/E7-S2-bravo")
    # Cleanup.
    _cli(sivale, "destroy", _A)
    _cli(sivale, "destroy", _B)


# --- AC-03: doctor identifies missing prerequisites (broken config) --------


def test_doctor_flags_bad_config(sivale: Path) -> None:
    (sivale / ".ramalio.toml").write_text(
        _SIVALE_LIKE.replace('base_branch = "main"', 'base_branch = "nonexistent"'),
        encoding="utf-8",
    )
    code, out, _ = _cli(sivale, "doctor")
    assert code == ExitCode.OPERATION_FAILED
    assert "Global: FAIL" in out


# --- migration docs exist (R10) --------------------------------------------


def test_migration_guide_present() -> None:
    guide = Path(__file__).resolve().parents[2] / "docs" / "sivale-migration.md"
    assert guide.is_file()
    text = guide.read_text(encoding="utf-8")
    # Teaches the standard CLI, not new project-specific wrappers (INV-4).
    # The migration guide must document the canonical executable `ramalio`.
    # Accepting the previous name would hide a regression to `imass-wt`.
    assert "ramalio init" in text
    assert "ramalio destroy" in text
