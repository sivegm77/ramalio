"""End-to-end and unit tests for `ramalio destroy` (E2-S3).

Covers CT-01..CT-11 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories.  The service is exercised directly (unit) and through the CLI
wrapper (integration) to prove the public contract.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.destroy import DestroyWorkspaceService
from ramalio.core.errors import (
    DestroyBlockedDirtyError,
    DestroyBranchInOtherWorktreeError,
    DestroyProtectedBranchError,
    DestroyWorktreeMismatchError,
    DestroyWorktreeRemoveFailedError,
    GitCommandError,
    WorkspaceNotFoundError,
)
from ramalio.core.result import ExitCode
from ramalio.git.lifecycle import GitWriter
from ramalio.git.repository import GitRepository

_CONFIG_PRESERVE = """
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

_CONFIG_DELETE = _CONFIG_PRESERVE + "delete_on_destroy = true\n"


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    """A real repository with a commit on main and a branch-preserving config."""

    write_config(git_repo_with_commit, _CONFIG_PRESERVE)
    return git_repo_with_commit


@pytest.fixture
def project_delete(git_repo_with_commit: Path, write_config) -> Path:
    """A real repository configured with delete_on_destroy = true."""

    write_config(git_repo_with_commit, _CONFIG_DELETE)
    return git_repo_with_commit


def _service(project_root: Path) -> DestroyWorkspaceService:
    return DestroyWorkspaceService(resolve_project_config(project_root))


def _wt_path(project_root: Path, target: str) -> Path:
    return (project_root / ".local-wt" / target).resolve()


def _add_worktree(run_git, project_root: Path, target: str) -> Path:
    wt = _wt_path(project_root, target)
    run_git(project_root, "worktree", "add", "-b", target, str(wt))
    return wt


# --- CT-01: clean, preserve branch (default) -------------------------------


def test_ct01_clean_preserve_branch(project: Path, run_git) -> None:
    wt = _add_worktree(run_git, project, "feature-one")

    outcome = _service(project).run("feature-one")

    repo = GitRepository.from_root(project)
    # AC-01: worktree removed.
    assert repo.get_worktree_by_path(wt) is None
    assert not wt.exists()
    # AC-05: branch preserved by default.
    assert repo.branch_exists("feature-one")
    assert outcome.worktree_removed is True
    assert outcome.branch_deleted is False
    assert outcome.branch_preserved_reason == "policy-disabled"


# --- CT-02: clean, safe branch delete (policy true) ------------------------


def test_ct02_clean_safe_branch_delete(project_delete: Path, run_git) -> None:
    # Branch merged into main (created from main, no new commits) -> safe to
    # delete non-force.
    wt = _add_worktree(run_git, project_delete, "feature-two")

    outcome = _service(project_delete).run("feature-two")

    repo = GitRepository.from_root(project_delete)
    # AC-06: worktree removed and safe branch deleted.
    assert repo.get_worktree_by_path(wt) is None
    assert not repo.branch_exists("feature-two")
    assert outcome.worktree_removed is True
    assert outcome.branch_deleted is True
    assert outcome.branch_preserved_reason is None


# --- CT-03: dirty tracked blocks -------------------------------------------


def test_ct03_dirty_tracked_blocks(project: Path, run_git) -> None:
    wt = _add_worktree(run_git, project, "feature-three")
    # Modify a tracked file (README.md exists from the seed commit).
    (wt / "README.md").write_text("changed\n", encoding="utf-8")

    with pytest.raises(DestroyBlockedDirtyError):
        _service(project).run("feature-three")

    # AC-02: nothing removed.
    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(wt) is not None
    assert repo.branch_exists("feature-three")


# --- CT-04: untracked blocks -----------------------------------------------


def test_ct04_untracked_blocks(project: Path, run_git) -> None:
    wt = _add_worktree(run_git, project, "feature-four")
    (wt / "new-file.txt").write_text("untracked\n", encoding="utf-8")

    with pytest.raises(DestroyBlockedDirtyError):
        _service(project).run("feature-four")

    # AC-03: nothing removed.
    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(wt) is not None


# --- CT-05: path mismatch blocks -------------------------------------------


def test_ct05_path_mismatch_blocks(project: Path, run_git) -> None:
    # Register the canonical path with a DIFFERENT branch than the derived one.
    wt = _wt_path(project, "feature-five")
    run_git(project, "worktree", "add", "-b", "other-branch", str(wt))
    run_git(project, "branch", "feature-five", "main")

    before_branches = _branches(project)
    with pytest.raises(DestroyWorktreeMismatchError):
        _service(project).run("feature-five")

    # AC-04: nothing removed.
    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(wt) is not None
    assert _branches(project) == before_branches


# --- CT-06: branch in other worktree blocks --------------------------------


def test_ct06_branch_in_other_worktree_blocks(project: Path, run_git) -> None:
    # Derived branch checked out at a non-canonical path, canonical path free.
    other = (project / ".local-wt" / "elsewhere").resolve()
    run_git(project, "worktree", "add", "-b", "feature-six", str(other))

    with pytest.raises(DestroyBranchInOtherWorktreeError):
        _service(project).run("feature-six")

    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(other) is not None


# --- CT-07: branch not safe to delete -> remove worktree, preserve branch --


def test_ct07_unmerged_branch_preserved(project_delete: Path, run_git) -> None:
    wt = _add_worktree(run_git, project_delete, "feature-seven")
    # Add a commit on the branch so it is NOT merged into main -> non-force
    # delete refuses (unsafe), branch must be preserved.
    (wt / "work.txt").write_text("real work\n", encoding="utf-8")
    run_git(wt, "add", "work.txt")
    run_git(wt, "commit", "-q", "-m", "unmerged work")

    outcome = _service(project_delete).run("feature-seven")

    repo = GitRepository.from_root(project_delete)
    # Worktree retired, branch preserved as a controlled partial closure (R13).
    assert repo.get_worktree_by_path(wt) is None
    assert repo.branch_exists("feature-seven")
    assert outcome.worktree_removed is True
    assert outcome.branch_deleted is False
    assert outcome.branch_preserved_reason == "not-safe-to-delete"


# --- CT-08: base branch collision blocks -----------------------------------


def test_ct08_base_branch_collision_blocks(project: Path) -> None:
    # A target whose derived branch collides with the base branch. With the
    # default pattern "{target}", target "main" derives branch "main", which is
    # the configured base branch and must be protected (R14).
    with pytest.raises(DestroyProtectedBranchError):
        _service(project).run("main")


# --- CT-09: worktree remove failure -> no branch delete --------------------


class _FailRemoveWriter(GitWriter):
    """Writer whose worktree removal always fails (CT-09)."""

    def remove_worktree(self, worktree_path: Path, *, force: bool = True) -> None:
        raise GitCommandError(
            "simulated worktree remove failure", args=("worktree", "remove")
        )


def test_ct09_worktree_remove_failure_skips_branch_delete(
    project_delete: Path, run_git
) -> None:
    wt = _add_worktree(run_git, project_delete, "feature-nine")
    config = resolve_project_config(project_delete)
    service = DestroyWorkspaceService(config, writer=_FailRemoveWriter(project_delete))

    with pytest.raises(DestroyWorktreeRemoveFailedError):
        service.run("feature-nine")

    # AC-09: branch not deleted because worktree removal failed.
    repo = GitRepository.from_root(project_delete)
    assert repo.branch_exists("feature-nine")
    assert repo.get_worktree_by_path(wt) is not None


# --- CT-10: second destroy -> WORKSPACE_NOT_FOUND --------------------------


def test_ct10_second_destroy_not_found(project_delete: Path, run_git) -> None:
    _add_worktree(run_git, project_delete, "feature-ten")
    _service(project_delete).run("feature-ten")

    # Branch was deleted (safe) and worktree removed; a second destroy finds
    # nothing.
    with pytest.raises(WorkspaceNotFoundError):
        _service(project_delete).run("feature-ten")


def test_ct10_second_destroy_not_found_preserve_variant(
    project: Path, run_git
) -> None:
    # With preserve policy, branch survives; but a second destroy still finds a
    # branch-only partial state, not a full workspace. It must not error as
    # not-found here because the branch remains. Removing the branch first makes
    # a true not-found.
    _add_worktree(run_git, project, "feature-ten-b")
    _service(project).run("feature-ten-b")
    repo = GitRepository.from_root(project)
    # Branch preserved -> branch-only state on second call (R3), not error.
    outcome = _service(project).run("feature-ten-b")
    assert outcome.worktree_removed is False
    assert repo.branch_exists("feature-ten-b")


# --- CT-11: no remote effects ----------------------------------------------


def test_ct11_destroy_issues_no_network_commands(
    project_delete: Path, run_git
) -> None:
    from ramalio.git.runner import GitRunner

    class _SpyRunner(GitRunner):
        def __init__(self, cwd) -> None:
            super().__init__(cwd)
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args, check=False, cwd=None):
            self.calls.append(tuple(args))
            return super().run(*args, check=check, cwd=cwd)

    _add_worktree(run_git, project_delete, "feature-net")
    config = resolve_project_config(project_delete)
    repo_spy = _SpyRunner(project_delete)
    writer_spy = _SpyRunner(project_delete)
    repo = GitRepository.from_root(project_delete, runner=repo_spy)
    writer = GitWriter(project_delete, runner=writer_spy)
    service = DestroyWorkspaceService(config, repository=repo, writer=writer)

    service.run("feature-net")

    forbidden = frozenset({"fetch", "pull", "push", "remote", "clone"})
    all_calls = repo_spy.calls + writer_spy.calls
    assert all_calls
    for argv in all_calls:
        assert argv and argv[0] not in forbidden, f"network command issued: {argv}"


# --- branch-only partial state (R3) ----------------------------------------


def test_branch_only_preserve(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-branch-only", "main")

    outcome = _service(project).run("feature-branch-only")

    assert outcome.worktree_removed is False
    assert outcome.branch_deleted is False
    repo = GitRepository.from_root(project)
    assert repo.branch_exists("feature-branch-only")


def test_branch_only_safe_delete(project_delete: Path, run_git) -> None:
    run_git(project_delete, "branch", "feature-branch-only-del", "main")

    outcome = _service(project_delete).run("feature-branch-only-del")

    assert outcome.worktree_removed is False
    assert outcome.branch_deleted is True
    repo = GitRepository.from_root(project_delete)
    assert not repo.branch_exists("feature-branch-only-del")


# --- config default (R10) --------------------------------------------------


def test_delete_on_destroy_defaults_false(project: Path) -> None:
    config = resolve_project_config(project)
    assert config.branch.delete_on_destroy is False


# --- CLI integration -------------------------------------------------------


def test_cli_destroy_clean_prints_structured_result(
    project: Path, monkeypatch, run_git
) -> None:
    _add_worktree(run_git, project, "feature-cli")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["destroy", "feature-cli"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "target: feature-cli" in out
    assert "worktree_removed: true" in out
    assert "branch_deleted: false" in out
    assert stderr.getvalue() == ""


def test_cli_destroy_not_found_maps_to_state_error(
    project: Path, monkeypatch
) -> None:
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["destroy", "feature-absent"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.STATE_ERROR
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("error: ")


def test_cli_destroy_dirty_maps_to_safety_blocked(
    project: Path, monkeypatch, run_git
) -> None:
    wt = _add_worktree(run_git, project, "feature-dirty-cli")
    (wt / "README.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["destroy", "feature-dirty-cli"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.SAFETY_BLOCKED
    assert stdout.getvalue() == ""


# --- helpers ---------------------------------------------------------------


def _branches(root: Path) -> tuple:
    import subprocess

    out = subprocess.run(
        ["git", "-C", str(root), "branch"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return tuple(
        sorted(
            line.strip().lstrip("* ").strip()
            for line in out.splitlines()
            if line.strip()
        )
    )
