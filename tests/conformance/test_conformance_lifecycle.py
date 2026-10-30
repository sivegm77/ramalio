"""End-to-end conformance: full lifecycle via the CLI across profiles (E7-S3).

Runs without Docker/tmux/zrok real tools (AC-01); exercises the public exit and
output contracts (R14/R15) deterministically (R17).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.core.result import ExitCode

from .harness import (
    PROFILE_GIT_ONLY,
    PROFILE_PROCESSES,
    PROFILE_RUNTIME_PORTS_TUNNEL,
    make_project,
)


# --- AC-02: happy-path lifecycle end-to-end (Git-only) ---------------------


def test_happy_path_lifecycle_git_only(tmp_path: Path) -> None:
    project = make_project(tmp_path, PROFILE_GIT_ONLY)

    # init
    r = project.run_cli("init", "feat-a")
    assert r.code == ExitCode.OK
    assert "target: feat-a" in r.stdout
    assert project.repo().branch_exists("feat-a")

    # list shows the workspace
    r = project.run_cli("list")
    assert r.code == ExitCode.OK
    assert "feat-a" in r.stdout

    # status READY
    r = project.run_cli("status", "feat-a")
    assert r.code == ExitCode.OK
    assert "State: READY" in r.stdout

    # stop / start (Git-only no-ops)
    assert project.run_cli("stop", "feat-a").code == ExitCode.OK
    assert project.run_cli("start", "feat-a").code == ExitCode.OK

    # destroy
    r = project.run_cli("destroy", "feat-a")
    assert r.code == ExitCode.OK
    assert "worktree_removed: true" in r.stdout
    assert project.repo().get_worktree_by_path(project.worktree_path("feat-a")) is None


# --- AC-06: the three profiles use the same core ---------------------------


@pytest.mark.parametrize(
    "profile",
    [PROFILE_GIT_ONLY, PROFILE_PROCESSES, PROFILE_RUNTIME_PORTS_TUNNEL],
)
def test_init_status_destroy_across_profiles(tmp_path: Path, profile: str) -> None:
    project = make_project(tmp_path, profile)
    try:
        assert project.run_cli("init", "feat-x").code == ExitCode.OK
        status = project.run_cli("status", "feat-x")
        assert status.code == ExitCode.OK
        assert "Target: feat-x" in status.stdout
    finally:
        # Always attempt teardown so process/tunnel profiles leave no residue.
        project.run_cli("destroy", "feat-x")


# --- adopt lifecycle (R6) --------------------------------------------------


def test_adopt_branch_only(tmp_path: Path) -> None:
    project = make_project(tmp_path, PROFILE_GIT_ONLY)
    project.git("branch", "feat-adopt", "main")
    r = project.run_cli("adopt", "feat-adopt")
    assert r.code == ExitCode.OK
    assert "adoption_mode: created-worktree" in r.stdout
    project.run_cli("destroy", "feat-adopt")


# --- exit contracts (R14) --------------------------------------------------


def test_exit_contracts_stable(tmp_path: Path) -> None:
    project = make_project(tmp_path, PROFILE_GIT_ONLY)
    # Unknown command -> usage error (2).
    assert project.run_cli("does-not-exist").code == ExitCode.USAGE_ERROR
    # status on a missing workspace is a successful diagnostic (0).
    assert project.run_cli("status", "absent").code == ExitCode.OK
    # destroy on a missing workspace -> state error (4).
    assert project.run_cli("destroy", "absent").code == ExitCode.STATE_ERROR


# --- doctor contract (R: pass/warn/fail) -----------------------------------


def test_doctor_healthy(tmp_path: Path) -> None:
    project = make_project(tmp_path, PROFILE_GIT_ONLY)
    r = project.run_cli("doctor")
    assert r.code == ExitCode.OK
    assert "Global: PASS" in r.stdout


def test_doctor_broken_config_fails(tmp_path: Path) -> None:
    project = make_project(tmp_path, PROFILE_GIT_ONLY)
    (project.root / ".ramalio.toml").write_text(
        PROFILE_GIT_ONLY.replace('base_branch = "main"', 'base_branch = "nope"'),
        encoding="utf-8",
    )
    r = project.run_cli("doctor")
    assert r.code == ExitCode.OPERATION_FAILED
    assert "Global: FAIL" in r.stdout


# --- determinism (R17) -----------------------------------------------------


def test_repeated_run_is_deterministic(tmp_path: Path) -> None:
    p1 = make_project(tmp_path / "a", PROFILE_GIT_ONLY)
    p2 = make_project(tmp_path / "b", PROFILE_GIT_ONLY)
    out1 = p1.run_cli("init", "feat-det").stdout
    out2 = p2.run_cli("init", "feat-det").stdout
    # Same structured fields (paths differ only by root, which we strip).
    def _fields(text: str) -> list[str]:
        return [
            line.split(":", 1)[0]
            for line in text.splitlines()
            if ":" in line
        ]

    assert _fields(out1) == _fields(out2)
    p1.run_cli("destroy", "feat-det")
    p2.run_cli("destroy", "feat-det")
