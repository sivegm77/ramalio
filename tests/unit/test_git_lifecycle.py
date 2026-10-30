"""Tests for the mutating Git write boundary (E2-S1 7.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.core.errors import GitCommandError
from ramalio.git.lifecycle import GitWriter
from ramalio.git.repository import GitRepository


def test_create_branch_starts_from_base_not_head(
    git_repo_with_commit: Path, run_git
) -> None:
    # Give HEAD a different tip than main so we can prove the new branch starts
    # from the explicit base, not from the invoking HEAD (R6).
    run_git(git_repo_with_commit, "checkout", "-q", "-b", "divergent")
    (git_repo_with_commit / "extra.txt").write_text("x\n", encoding="utf-8")
    run_git(git_repo_with_commit, "add", "extra.txt")
    run_git(git_repo_with_commit, "commit", "-q", "-m", "divergent tip")

    writer = GitWriter(git_repo_with_commit)
    writer.create_branch(branch="feature-a", base="main")

    repo = GitRepository.from_root(git_repo_with_commit)
    main = repo.get_branch("main")
    feature = repo.get_branch("feature-a")
    assert feature is not None and main is not None
    assert feature.commit == main.commit  # started from base, not divergent HEAD


def test_create_branch_fails_closed_when_branch_exists(
    git_repo_with_commit: Path, run_git
) -> None:
    run_git(git_repo_with_commit, "branch", "existing", "main")
    writer = GitWriter(git_repo_with_commit)
    with pytest.raises(GitCommandError):
        writer.create_branch(branch="existing", base="main")


def test_add_worktree_for_branch_registers_worktree(
    git_repo_with_commit: Path
) -> None:
    writer = GitWriter(git_repo_with_commit)
    writer.create_branch(branch="feature-b", base="main")
    wt_path = git_repo_with_commit / ".local-wt" / "feature-b"
    writer.add_worktree_for_branch(branch="feature-b", worktree_path=wt_path)

    repo = GitRepository.from_root(git_repo_with_commit)
    registered = repo.get_worktree_by_path(wt_path)
    assert registered is not None
    assert registered.branch == "feature-b"


def test_remove_worktree_and_delete_branch_round_trip(
    git_repo_with_commit: Path
) -> None:
    writer = GitWriter(git_repo_with_commit)
    writer.create_branch(branch="temp", base="main")
    wt_path = git_repo_with_commit / ".local-wt" / "temp"
    writer.add_worktree_for_branch(branch="temp", worktree_path=wt_path)

    writer.remove_worktree(wt_path, force=True)
    writer.prune_worktrees()
    writer.delete_branch("temp", force=True)

    repo = GitRepository.from_root(git_repo_with_commit)
    assert repo.get_worktree_by_path(wt_path) is None
    assert not repo.branch_exists("temp")


def test_create_worktree_with_branch_atomic_form(git_repo_with_commit: Path) -> None:
    writer = GitWriter(git_repo_with_commit)
    wt_path = git_repo_with_commit / ".local-wt" / "atomic"
    writer.create_worktree_with_branch(
        branch="atomic", worktree_path=wt_path, base="main"
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    registered = repo.get_worktree_by_path(wt_path)
    assert registered is not None and registered.branch == "atomic"
