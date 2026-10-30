from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.core.errors import BaseBranchNotFoundError
from ramalio.git.repository import GitRepository


def test_get_root_matches_repository(git_repo_with_commit: Path) -> None:
    # AC-01 — the boundary identifies the Git root correctly.
    repo = GitRepository.from_root(git_repo_with_commit)
    assert repo.get_root() == git_repo_with_commit.resolve()


def test_ensure_valid_accepts_working_tree(git_repo_with_commit: Path) -> None:
    repo = GitRepository.from_root(git_repo_with_commit)
    repo.ensure_valid()  # does not raise


def test_resolve_base_branch_present(git_repo_with_commit: Path) -> None:
    # CT-01 — repo with main resolves the base branch.
    repo = GitRepository.from_root(git_repo_with_commit)
    base = repo.resolve_base_branch("main")
    assert base.name == "main"
    assert len(base.commit) == 40


def test_resolve_base_branch_missing_raises(git_repo_with_commit: Path) -> None:
    # CT-02 — base branch does not exist locally.
    repo = GitRepository.from_root(git_repo_with_commit)
    with pytest.raises(BaseBranchNotFoundError) as excinfo:
        repo.resolve_base_branch("develop")
    assert excinfo.value.code == "BASE_BRANCH_NOT_FOUND"


def test_branch_exists_positive_and_negative(
    git_repo_with_commit: Path, run_git
) -> None:
    # CT-03 — a created branch is reported present, an unknown one absent.
    run_git(git_repo_with_commit, "branch", "feature-x")
    repo = GitRepository.from_root(git_repo_with_commit)
    assert repo.branch_exists("feature-x") is True
    assert repo.branch_exists("nope") is False
    branch = repo.get_branch("feature-x")
    assert branch is not None
    assert branch.name == "feature-x"


def test_resolve_ref_returns_commit_or_none(git_repo_with_commit: Path) -> None:
    repo = GitRepository.from_root(git_repo_with_commit)
    commit = repo.resolve_ref("main")
    assert commit is not None and len(commit) == 40
    assert repo.resolve_ref("missing-ref") is None


def test_list_worktrees_includes_additional(
    git_repo_with_commit: Path, run_git
) -> None:
    # CT-04 — an additional worktree is listed with its branch/path.
    wt_path = git_repo_with_commit / ".local-wt" / "feature"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    worktrees = repo.list_worktrees()
    paths = {wt.path for wt in worktrees}
    assert git_repo_with_commit.resolve() in paths
    assert wt_path.resolve() in paths
    by_path = repo.get_worktree_by_path(wt_path)
    assert by_path is not None
    assert by_path.branch == "feature-x"


def test_branch_checked_out_detected(git_repo_with_commit: Path, run_git) -> None:
    # CT-05 — a branch checked out in another worktree is detected.
    wt_path = git_repo_with_commit / ".local-wt" / "feature"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )
    repo = GitRepository.from_root(git_repo_with_commit)
    found = repo.get_worktree_by_branch("feature-x")
    assert found is not None
    assert found.path == wt_path.resolve()
    assert repo.branch_checked_out_elsewhere("feature-x") is not None


def test_status_dirty_tracked_file(git_repo_with_commit: Path) -> None:
    # CT-06 — a modified tracked file is reported dirty.
    (git_repo_with_commit / "README.md").write_text("changed\n", encoding="utf-8")
    repo = GitRepository.from_root(git_repo_with_commit)
    status = repo.get_status()
    assert status.dirty is True
    assert status.clean is False


def test_status_untracked_file(git_repo_with_commit: Path) -> None:
    # CT-07 — an untracked file is reported.
    (git_repo_with_commit / "new.txt").write_text("hello\n", encoding="utf-8")
    repo = GitRepository.from_root(git_repo_with_commit)
    status = repo.get_status()
    assert status.untracked is True


def test_status_detached_head(git_repo_with_commit: Path, run_git) -> None:
    # CT-08 — a detached HEAD is observed correctly.
    commit = run_git(git_repo_with_commit, "rev-parse", "HEAD").strip()
    run_git(git_repo_with_commit, "checkout", "-q", "--detach", commit)
    repo = GitRepository.from_root(git_repo_with_commit)
    status = repo.get_status()
    assert status.detached is True


def test_status_clean_repository(git_repo_with_commit: Path) -> None:
    repo = GitRepository.from_root(git_repo_with_commit)
    status = repo.get_status()
    assert status.clean is True
    assert status.detached is False
