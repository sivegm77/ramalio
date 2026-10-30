"""End-to-end and unit tests for `ramalio doctor` (E3-S3).

Covers CT-01..CT-12 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories, healthy and broken.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.core.doctor import (
    CheckStatus,
    DoctorService,
)
from ramalio.core.result import ExitCode
from ramalio.git.runner import GitRunner

_CONFIG_BODY = """
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "{target}"
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _CONFIG_BODY)
    return git_repo_with_commit


def _report(project_root: Path):
    return DoctorService(start=project_root).run()


def _status_of(report, check_id: str) -> CheckStatus:
    for r in report.results:
        if r.check_id == check_id:
            return r.status
    raise AssertionError(f"check {check_id} not found")


# --- CT-01: healthy project -> PASS ----------------------------------------


def test_ct01_healthy_project_pass(project: Path) -> None:
    report = _report(project)
    assert report.global_status == CheckStatus.PASS
    assert report.exit_code == ExitCode.OK
    # AC-01: readiness derived true.
    assert report.readiness.ready_for_init is True


# --- CT-03: not a repo -> FAIL (git available but not a repository) --------


def test_ct03_not_a_repo_fail(tmp_path: Path) -> None:
    report = DoctorService(start=tmp_path).run()
    assert report.global_status == CheckStatus.FAIL
    assert report.exit_code == ExitCode.OPERATION_FAILED
    assert _status_of(report, "GIT_REPOSITORY") == CheckStatus.FAIL
    # Config checks skip because there is no repository root.
    assert _status_of(report, "CONFIG_PRESENT") == CheckStatus.SKIP


# --- CT-04: missing TOML -> FAIL -------------------------------------------


def test_ct04_missing_toml_fail(git_repo_with_commit: Path) -> None:
    report = _report(git_repo_with_commit)
    assert _status_of(report, "CONFIG_PRESENT") == CheckStatus.FAIL
    assert report.global_status == CheckStatus.FAIL


# --- CT-05: invalid TOML -> FAIL -------------------------------------------


def test_ct05_invalid_toml_fail(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, "this is = not valid = toml [[[")
    report = _report(git_repo_with_commit)
    assert _status_of(report, "CONFIG_VALID") == CheckStatus.FAIL
    assert report.global_status == CheckStatus.FAIL


# --- CT-06: base branch missing -> FAIL ------------------------------------


def test_ct06_base_branch_missing_fail(
    git_repo_with_commit: Path, write_config
) -> None:
    body = _CONFIG_BODY.replace('base_branch = "main"', 'base_branch = "develop"')
    write_config(git_repo_with_commit, body)
    report = _report(git_repo_with_commit)
    assert _status_of(report, "BASE_BRANCH") == CheckStatus.FAIL
    assert report.global_status == CheckStatus.FAIL


# --- CT-07: bad target regex/example -> FAIL -------------------------------


def test_ct07_bad_target_example_fail(
    git_repo_with_commit: Path, write_config
) -> None:
    # Example does not match the regex.
    body = _CONFIG_BODY.replace('example = "my-feature"', 'example = "Invalid Example"')
    write_config(git_repo_with_commit, body)
    report = _report(git_repo_with_commit)
    assert _status_of(report, "TARGET_POLICY") == CheckStatus.FAIL
    assert report.global_status == CheckStatus.FAIL


# --- CT-08: bad branch pattern -> FAIL -------------------------------------


def test_ct08_bad_branch_pattern_fail(
    git_repo_with_commit: Path, write_config
) -> None:
    # Pattern missing {target} -> invalid.
    body = _CONFIG_BODY.replace('pattern = "{target}"\n', 'pattern = "static-branch"\n', 1)
    # Ensure only the branch pattern changed; keep worktree pattern valid.
    body = """
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "no-placeholder"
"""
    write_config(git_repo_with_commit, body)
    report = _report(git_repo_with_commit)
    assert _status_of(report, "BRANCH_PATTERN") == CheckStatus.FAIL
    assert report.global_status == CheckStatus.FAIL


# --- CT-09: unsafe worktree pattern -> FAIL --------------------------------


def test_ct09_unsafe_worktree_pattern_fail(
    git_repo_with_commit: Path, write_config
) -> None:
    body = """
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "../{target}"

[branch]
pattern = "{target}"
"""
    write_config(git_repo_with_commit, body)
    report = _report(git_repo_with_commit)
    assert _status_of(report, "WORKTREE_PATTERN") == CheckStatus.FAIL


# --- CT-10 / CT-11: worktree anomalies -> WARN -----------------------------


def test_ct10_inconsistent_worktree_warn(project: Path, run_git) -> None:
    # Branch derives target but the worktree is at a non-canonical path.
    other = (project / ".local-wt" / "wrong").resolve()
    run_git(project, "worktree", "add", "-b", "feature-x", str(other))

    report = _report(project)
    assert _status_of(report, "WORKTREES") == CheckStatus.WARN
    # AC-09: warnings do not produce an error exit code.
    assert report.global_status == CheckStatus.WARN
    assert report.exit_code == ExitCode.OK


def test_ct11_prunable_worktree_warn(project: Path, run_git) -> None:
    wt = (project / ".local-wt" / "feature-prune").resolve()
    run_git(project, "worktree", "add", "-b", "feature-prune", str(wt))
    import shutil

    shutil.rmtree(wt)

    report = _report(project)
    assert _status_of(report, "WORKTREES") == CheckStatus.WARN


# --- CT-02: git missing -> FAIL + dependent skips --------------------------


def test_ct02_git_missing_fail_and_skips(project: Path, monkeypatch) -> None:
    import ramalio.core.doctor as doctor_mod

    # Simulate git not being available anywhere.
    monkeypatch.setattr(doctor_mod.shutil, "which", lambda _name: None)
    report = DoctorService(start=project).run()

    assert _status_of(report, "GIT_AVAILABLE") == CheckStatus.FAIL
    assert _status_of(report, "GIT_REPOSITORY") == CheckStatus.SKIP
    # AC-02: dependent checks skip.
    assert report.global_status == CheckStatus.FAIL


# --- CT-12: read-only proof -------------------------------------------------


def test_ct12_doctor_read_only(project: Path, run_git) -> None:
    run_git(project, "worktree", "add", "-b", "feature-ro", str(
        (project / ".local-wt" / "feature-ro").resolve()
    ))
    before = sorted(str(p) for p in project.rglob("*"))
    _report(project)
    after = sorted(str(p) for p in project.rglob("*"))
    # AC-10: no filesystem mutations.
    assert after == before


# --- aggregation unit checks -----------------------------------------------


def test_warn_does_not_override_fail(project: Path, run_git) -> None:
    # Introduce both a WARN (anomalous worktree) and a FAIL (missing base
    # branch) and confirm FAIL wins.
    other = (project / ".local-wt" / "wrong").resolve()
    run_git(project, "worktree", "add", "-b", "feature-x", str(other))
    # Break base branch via config rewrite.
    (project / ".ramalio.toml").write_text(
        _CONFIG_BODY.replace('base_branch = "main"', 'base_branch = "nope"'),
        encoding="utf-8",
    )
    report = _report(project)
    assert report.global_status == CheckStatus.FAIL


# --- extensibility ----------------------------------------------------------


def test_register_additional_check(project: Path) -> None:
    from ramalio.core.doctor import (
        DoctorSection,
        DoctorCheckResult,
    )

    def extra_check(_ctx) -> DoctorCheckResult:
        return DoctorCheckResult(
            check_id="EXTRA",
            section=DoctorSection.EXTENSIONS,
            status=CheckStatus.PASS,
            summary="custom check",
        )

    service = DoctorService(start=project)
    service.register(extra_check)
    report = service.run()
    assert any(r.check_id == "EXTRA" for r in report.results)


# --- CLI integration -------------------------------------------------------


def test_cli_doctor_healthy_success(project: Path, monkeypatch) -> None:
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["doctor"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "[Environment]" in out
    assert "GIT_AVAILABLE" in out
    assert "Global: PASS" in out
    assert "ready_for_init: true" in out


def test_cli_doctor_broken_config_nonzero(
    git_repo_with_commit: Path, monkeypatch
) -> None:
    monkeypatch.chdir(git_repo_with_commit)  # no config file
    stdout, stderr = StringIO(), StringIO()
    code = main(["doctor"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OPERATION_FAILED
    assert "Global: FAIL" in stdout.getvalue()



# --- P9 (E7-S1 R10/R16): doctor ignores released-but-leftover lock files ---


def test_locks_check_ignores_released_leftover_lock_file(
    project: Path, tmp_path: Path, monkeypatch
) -> None:
    """A lock file persists on disk after its holder releases it. doctor must
    classify locks by whether the OS lock is actually held, not by the mere
    presence of the file or a still-alive PID, so a released lock is not
    reported as active/stale (E7-S1 R10/R16)."""

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    from ramalio.resources.locks import LockKey, LockManager, LockScope

    mgr = LockManager.for_repository(project)
    key = LockKey(LockScope.TARGET, f"{project}:feat-a")
    # Acquire and release: leaves the .lock FILE on disk but the flock is free.
    with mgr.acquire(key, operation="init"):
        pass

    report = _report(project)
    locks = [r for r in report.results if r.check_id == "LOCKS"]
    assert locks, "doctor should include a LOCKS check"
    assert locks[0].status == CheckStatus.PASS
    assert "no lifecycle locks held" in locks[0].summary


def test_locks_check_reports_held_lock(
    project: Path, tmp_path: Path, monkeypatch
) -> None:
    """While a lock is genuinely held, doctor reports it as active."""

    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    from ramalio.resources.locks import LockKey, LockManager, LockScope

    mgr = LockManager.for_repository(project)
    key = LockKey(LockScope.TARGET, f"{project}:feat-a")
    with mgr.acquire(key, operation="init"):
        report = _report(project)
    locks = [r for r in report.results if r.check_id == "LOCKS"]
    assert locks
    # The current process holds it and is alive -> active, not stale.
    assert "active" in locks[0].summary.lower()
