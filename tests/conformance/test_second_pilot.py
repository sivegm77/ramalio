"""Second pilot project conformance — SYNTHETIC generality fixture (E9-S0).

A materially different profile from SiVale (Git-only Python library/CLI: no
runtime/ports/tmux/Kiro/zrok, different target and branch naming) proving the
core is not coupled to the first pilot.  Same public CLI, configuration-only
adoption (INV-01/INV-02/INV-03).

SCOPE AND LIMITS (read before citing this as E9-S0 closure):
    ``pylib-tools`` is a *synthetic* project built inside the test fixture
    (``git init`` + a seed commit + the example TOML).  It demonstrates that the
    core supports a second, materially different *profile* — which is genuinely
    valuable — but it is NOT the same as a real second iMass project adopting
    ``ramalio`` and operating with it day to day.  E9-S0 requires the
    latter (§2, R2, R12: inventory a real project's lifecycle and operate it
    without project knowledge in the core).  Use
    ``docs/second-pilot-checklist.md`` to run that real adoption and record its
    evidence; keep this fixture as a permanent conformance profile, not as
    substitute evidence.
"""

from __future__ import annotations

import os
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import (
    build_target_normalizer,
    build_workspace_naming,
)
from ramalio.core.result import ExitCode
from ramalio.git.repository import GitRepository

_PILOT_TOML = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "second-pilot.ramalio.toml"
).read_text(encoding="utf-8")

_A = "issue-142-add-retry-helper"
_B = "issue-7-fix-typo"


@pytest.fixture
def pilot(tmp_path: Path) -> Path:
    root = tmp_path / "pylib"
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
    (root / "README.md").write_text("lib\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    (root / ".ramalio.toml").write_text(_PILOT_TOML, encoding="utf-8")
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


# --- AC-02: config loads without core changes ------------------------------


def test_ac02_config_loads(pilot: Path) -> None:
    config = resolve_project_config(pilot)
    assert config.project.name == "pylib-tools"
    assert config.branch.pattern == "wt/{target}"
    assert config.worktree.directory == ".worktrees"
    # No capabilities/ports configured (AC-09).
    assert dict(config.capabilities) == {}
    assert config.ports.enabled is False


# --- AC-01/R4: a different target convention validates ---------------------


def test_ac01_different_target(pilot: Path) -> None:
    config = resolve_project_config(pilot)
    normalizer = build_target_normalizer(config)
    result = normalizer.normalize("issue-142-Add-Retry-Helper")
    assert result.target.value == "issue-142-add-retry-helper"
    naming = build_workspace_naming(config)
    identity = naming.resolve(result.target)
    assert identity.branch_name == "wt/issue-142-add-retry-helper"
    assert str(identity.worktree_path) == ".worktrees/issue-142-add-retry-helper"


def test_sivale_target_rejected_here(pilot: Path) -> None:
    from ramalio.core.errors import TargetInvalidError

    config = resolve_project_config(pilot)
    normalizer = build_target_normalizer(config)
    # A SiVale-style target does not match this project's convention.
    with pytest.raises(TargetInvalidError):
        normalizer.normalize("E7-S8-convergencia")


# --- AC-03: doctor healthy (Git-only, no external tools) -------------------


def test_ac03_doctor_healthy(pilot: Path) -> None:
    code, out, _ = _cli(pilot, "doctor")
    assert code == ExitCode.OK
    assert "Global: PASS" in out


# --- AC-04..AC-08: full lifecycle via the same CLI -------------------------


def test_full_lifecycle(pilot: Path) -> None:
    # init (AC-04)
    code, out, err = _cli(pilot, "init", _A)
    assert code == ExitCode.OK, err
    assert "branch: wt/issue-142-add-retry-helper" in out

    # list + status (AC-06)
    assert _A in _cli(pilot, "list")[1]
    assert "State: READY" in _cli(pilot, "status", _A)[1]

    # start/stop are no-ops here (no capabilities) (AC-07)
    assert _cli(pilot, "stop", _A)[0] == ExitCode.OK
    assert _cli(pilot, "start", _A)[0] == ExitCode.OK

    # destroy: branch deletable (created from main, delete_on_destroy=true) (AC-08)
    code, out, _ = _cli(pilot, "destroy", _A)
    assert code == ExitCode.OK
    g = GitRepository.from_root(pilot)
    assert g.get_worktree_by_path((pilot / ".worktrees" / _A).resolve()) is None
    assert not g.branch_exists("wt/issue-142-add-retry-helper")


# --- AC-05: adopt existing branch-only work --------------------------------


def test_ac05_adopt(pilot: Path) -> None:
    subprocess.run(
        ["git", "-C", str(pilot), "branch", "wt/issue-7-fix-typo", "main"],
        check=True,
        capture_output=True,
    )
    code, out, _ = _cli(pilot, "adopt", "issue-7-fix-typo")
    assert code == ExitCode.OK
    assert "adoption_mode: created-worktree" in out
    _cli(pilot, "destroy", "issue-7-fix-typo")


# --- AC-07/R7: parallel workspaces isolated --------------------------------


def test_parallel_isolated(pilot: Path) -> None:
    assert _cli(pilot, "init", _A)[0] == ExitCode.OK
    assert _cli(pilot, "init", _B)[0] == ExitCode.OK
    g = GitRepository.from_root(pilot)
    assert g.branch_exists("wt/issue-142-add-retry-helper")
    assert g.branch_exists("wt/issue-7-fix-typo")
    assert g.get_worktree_by_path((pilot / ".worktrees" / _A).resolve()) is not None
    assert g.get_worktree_by_path((pilot / ".worktrees" / _B).resolve()) is not None
    _cli(pilot, "destroy", _A)
    _cli(pilot, "destroy", _B)


# --- AC-08: destroy blocks dirty work --------------------------------------


def test_ac08_destroy_blocks_dirty(pilot: Path) -> None:
    _cli(pilot, "init", _A)
    (pilot / ".worktrees" / _A / "new.txt").write_text("wip\n", encoding="utf-8")
    code, out, err = _cli(pilot, "destroy", _A)
    # Untracked work blocks destroy (safety), non-zero exit.
    assert code == ExitCode.SAFETY_BLOCKED
    assert GitRepository.from_root(pilot).get_worktree_by_path(
        (pilot / ".worktrees" / _A).resolve()
    ) is not None
