"""End-to-end and unit tests for `ramalio status` (E3-S1).

Covers CT-01..CT-10 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.status import (
    GetWorkspaceStatusService,
    SuggestedAction,
    WorkspaceState,
)
from ramalio.core.result import ExitCode
from ramalio.git.repository import GitRepository
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


def _service(project_root: Path) -> GetWorkspaceStatusService:
    return GetWorkspaceStatusService(resolve_project_config(project_root))


def _wt(project_root: Path, target: str) -> Path:
    return (project_root / ".local-wt" / target).resolve()


def _add(run_git, project_root: Path, target: str) -> Path:
    wt = _wt(project_root, target)
    run_git(project_root, "worktree", "add", "-b", target, str(wt))
    return wt


# --- CT-01: READY ----------------------------------------------------------


def test_ct01_ready(project: Path, run_git) -> None:
    _add(run_git, project, "feature-one")
    status = _service(project).run("feature-one")

    assert status.state == WorkspaceState.READY
    assert status.suggested_action == SuggestedAction.NONE
    # AC-09: expected vs observed.
    assert status.identity.expected_branch == "feature-one"
    assert status.observed.worktree_branch == "feature-one"
    assert status.destroy_safety.safe is True


# --- CT-02: DIRTY tracked -> destroy false ---------------------------------


def test_ct02_dirty_tracked_blocks_destroy(project: Path, run_git) -> None:
    wt = _add(run_git, project, "feature-two")
    (wt / "README.md").write_text("changed\n", encoding="utf-8")

    status = _service(project).run("feature-two")
    assert status.state == WorkspaceState.DIRTY
    # AC-08: dirty blocks destroy_safe.
    assert status.destroy_safety.safe is False
    assert "DIRTY_TRACKED_CHANGES" in status.destroy_safety.blockers


# --- CT-03: untracked -> DIRTY ---------------------------------------------


def test_ct03_untracked_dirty(project: Path, run_git) -> None:
    wt = _add(run_git, project, "feature-three")
    (wt / "extra.txt").write_text("x\n", encoding="utf-8")

    status = _service(project).run("feature-three")
    assert status.state == WorkspaceState.DIRTY
    assert "UNTRACKED_FILES" in status.destroy_safety.blockers


# --- CT-04: BRANCH_ONLY -> adopt -------------------------------------------


def test_ct04_branch_only_adopt(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-four", "main")
    status = _service(project).run("feature-four")

    assert status.state == WorkspaceState.BRANCH_ONLY
    assert status.suggested_action == SuggestedAction.ADOPT
    assert status.observed.branch_exists is True
    assert status.observed.worktree_registered is False


# --- CT-05: MISSING -> init ------------------------------------------------


def test_ct05_missing_init(project: Path) -> None:
    status = _service(project).run("feature-five")

    assert status.state == WorkspaceState.MISSING
    assert status.suggested_action == SuggestedAction.INIT
    assert status.observed.branch_exists is False
    assert status.git is None


# --- CT-06: wrong path -> inconsistent -------------------------------------


def test_ct06_branch_in_other_worktree_inconsistent(project: Path, run_git) -> None:
    other = (project / ".local-wt" / "elsewhere").resolve()
    run_git(project, "worktree", "add", "-b", "feature-six", str(other))

    status = _service(project).run("feature-six")
    assert status.state == WorkspaceState.INCONSISTENT
    assert status.reason == "BRANCH_IN_OTHER_WORKTREE"
    assert status.suggested_action == SuggestedAction.INSPECT
    assert status.destroy_safety.safe is False


# --- CT-07: wrong branch at canonical path -> inconsistent -----------------


def test_ct07_branch_mismatch_inconsistent(project: Path, run_git) -> None:
    wt = _wt(project, "feature-seven")
    run_git(project, "worktree", "add", "-b", "other-branch", str(wt))

    status = _service(project).run("feature-seven")
    assert status.state == WorkspaceState.INCONSISTENT
    assert status.reason == "WORKTREE_BRANCH_MISMATCH"


# --- CT-08: detached -------------------------------------------------------


def test_ct08_detached(project: Path, run_git) -> None:
    wt = _wt(project, "feature-eight")
    head = run_git(project, "rev-parse", "HEAD").strip()
    run_git(project, "worktree", "add", "--detach", str(wt), head)

    status = _service(project).run("feature-eight")
    assert status.state == WorkspaceState.DETACHED
    assert status.reason == "WORKTREE_DETACHED"
    assert status.suggested_action == SuggestedAction.INSPECT


# --- CT-09: prunable -------------------------------------------------------


def test_ct09_prunable(project: Path, run_git) -> None:
    wt = _add(run_git, project, "feature-nine")
    import shutil

    shutil.rmtree(wt)

    status = _service(project).run("feature-nine")
    assert status.state == WorkspaceState.PRUNABLE
    assert status.reason == "WORKTREE_PRUNABLE"


# --- CT-10: read-only ------------------------------------------------------


def test_ct10_status_issues_no_mutations(project: Path, run_git) -> None:
    class _SpyRunner(GitRunner):
        def __init__(self, cwd) -> None:
            super().__init__(cwd)
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args, check=False, cwd=None):
            self.calls.append(tuple(args))
            return super().run(*args, check=check, cwd=cwd)

    _add(run_git, project, "feature-ten")
    spy = _SpyRunner(project)
    repo = GitRepository.from_root(project, runner=spy)
    service = GetWorkspaceStatusService(
        resolve_project_config(project), repository=repo
    )
    service.run("feature-ten")

    forbidden_first = frozenset({"fetch", "pull", "push", "remote", "clone"})
    for argv in spy.calls:
        assert argv
        assert argv[0] not in forbidden_first, f"network command: {argv}"
        if argv[0] == "worktree":
            assert argv[1] == "list", f"mutating worktree command: {argv}"


# --- base branch protection ------------------------------------------------


def test_base_branch_protected_blocks_destroy(project: Path, run_git) -> None:
    # target "main" derives branch "main" == base branch.
    status = _service(project).run("main")
    assert "PROTECTED_BASE_BRANCH" in status.destroy_safety.blockers


# --- capabilities slot reserved (R14) --------------------------------------


def test_capabilities_slot_empty(project: Path, run_git) -> None:
    _add(run_git, project, "feature-cap")
    status = _service(project).run("feature-cap")
    assert status.capabilities == ()


# --- CLI integration -------------------------------------------------------


def test_cli_status_ready_prints_detail(project: Path, monkeypatch, run_git) -> None:
    _add(run_git, project, "feature-cli")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["status", "feature-cli"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "Target: feature-cli" in out
    assert "State: READY" in out
    assert "Destroy safe: yes" in out
    assert "Suggested action: none" in out
    assert stderr.getvalue() == ""


def test_cli_status_missing_is_success(project: Path, monkeypatch) -> None:
    # R15: missing workspace is a successful diagnostic, not an error.
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["status", "feature-absent"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    assert "State: MISSING" in stdout.getvalue()
    assert "Suggested action: init" in stdout.getvalue()
