from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from ramalio.core.naming import ResolvedWorkspaceIdentity
from ramalio.core.target import Target
from ramalio.core.worktree import WorkspaceObserver
from ramalio.git.repository import GitRepository


def _identity(branch: str, rel_path: str) -> ResolvedWorkspaceIdentity:
    return ResolvedWorkspaceIdentity(
        target=Target.from_trusted(branch),
        branch_name=branch,
        worktree_path=PurePosixPath(rel_path),
    )


def test_observe_no_branch_no_worktree(git_repo_with_commit: Path) -> None:
    repo = GitRepository.from_root(git_repo_with_commit)
    observer = WorkspaceObserver(repo)
    identity = _identity("feature-x", ".local-wt/feature")
    observed = observer.observe(identity)
    assert observed.branch_exists is False
    assert observed.worktree_exists is False
    assert observed.worktree is None
    assert observed.git_status is None


def test_observe_existing_worktree(git_repo_with_commit: Path, run_git) -> None:
    wt_path = git_repo_with_commit / ".local-wt" / "feature"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    observer = WorkspaceObserver(repo)
    identity = _identity("feature-x", ".local-wt/feature")
    observed = observer.observe(identity)
    assert observed.branch_exists is True
    assert observed.worktree_exists is True
    assert observed.worktree_branch == "feature-x"
    assert observed.branch_checked_out_here is True
    assert observed.git_status is not None
    assert observed.git_status.clean is True


def test_branch_collision_fact(git_repo_with_commit: Path, run_git) -> None:
    # R9 — the derived branch already exists; only the fact is reported.
    run_git(git_repo_with_commit, "branch", "feature-x")
    repo = GitRepository.from_root(git_repo_with_commit)
    observer = WorkspaceObserver(repo)
    identity = _identity("feature-x", ".local-wt/feature")
    assert observer.branch_collision(identity) is True


def test_worktree_path_registered(git_repo_with_commit: Path, run_git) -> None:
    # CT-09 — a path registered as worktree is detected.
    wt_path = git_repo_with_commit / ".local-wt" / "feature"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    observer = WorkspaceObserver(repo)
    identity = _identity("feature-x", ".local-wt/feature")
    registered = observer.worktree_path_registered(identity)
    assert registered is not None
    assert registered.path == wt_path.resolve()
    assert observer.worktree_path_exists(identity) is True


def test_branch_used_by_other_worktree(git_repo_with_commit: Path, run_git) -> None:
    # R11 — the branch is checked out in a worktree other than the identity path.
    wt_path = git_repo_with_commit / ".local-wt" / "other"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    observer = WorkspaceObserver(repo)
    identity = _identity("feature-x", ".local-wt/feature")
    other = observer.branch_used_by_other_worktree(identity)
    assert other is not None
    assert other.path == wt_path.resolve()


def test_branch_used_only_at_own_path_returns_none(
    git_repo_with_commit: Path, run_git
) -> None:
    wt_path = git_repo_with_commit / ".local-wt" / "feature"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    observer = WorkspaceObserver(repo)
    identity = _identity("feature-x", ".local-wt/feature")
    assert observer.branch_used_by_other_worktree(identity) is None
