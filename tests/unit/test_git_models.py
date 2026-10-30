from __future__ import annotations

from pathlib import Path

from ramalio.git.models import CheckoutState, GitStatus, WorktreeInfo
from ramalio.git.repository import (
    _parse_status_porcelain,
    _parse_worktree_porcelain,
)


def test_git_status_clean_summary() -> None:
    status = GitStatus(dirty=False, untracked=False, detached=False)
    assert status.clean is True
    assert status.state is CheckoutState.CLEAN


def test_git_status_dirty_summary() -> None:
    status = GitStatus(dirty=True, untracked=False, detached=False)
    assert status.clean is False
    assert status.state is CheckoutState.DIRTY


def test_worktree_info_detached_derivation() -> None:
    detached = WorktreeInfo(path=Path("/wt"), head="abc", branch=None)
    assert detached.is_detached is True
    attached = WorktreeInfo(path=Path("/wt"), head="abc", branch="feature")
    assert attached.is_detached is False


def test_parse_worktree_porcelain_multiple_records() -> None:
    text = (
        "worktree /repo\n"
        "HEAD 1111111111111111111111111111111111111111\n"
        "branch refs/heads/main\n"
        "\n"
        "worktree /repo/.local-wt/feature\n"
        "HEAD 2222222222222222222222222222222222222222\n"
        "branch refs/heads/feature-x\n"
        "\n"
        "worktree /repo/.local-wt/detached\n"
        "HEAD 3333333333333333333333333333333333333333\n"
        "detached\n"
    )
    worktrees = _parse_worktree_porcelain(text)
    assert len(worktrees) == 3
    assert worktrees[0].branch == "main"
    assert worktrees[1].branch == "feature-x"
    assert worktrees[2].branch is None
    assert worktrees[2].detached is True


def test_parse_worktree_porcelain_locked_and_prunable() -> None:
    text = (
        "worktree /repo/.local-wt/locked\n"
        "HEAD 4444444444444444444444444444444444444444\n"
        "branch refs/heads/locked-branch\n"
        "locked reason here\n"
        "prunable gitdir file points to non-existent location\n"
    )
    (worktree,) = _parse_worktree_porcelain(text)
    assert worktree.locked is True
    assert worktree.prunable is True


def test_parse_status_porcelain_clean() -> None:
    status = _parse_status_porcelain("## main...origin/main\n")
    assert status.clean is True
    assert status.detached is False


def test_parse_status_porcelain_dirty_and_untracked() -> None:
    text = "## main\n M tracked.txt\n?? untracked.txt\n"
    status = _parse_status_porcelain(text)
    assert status.dirty is True
    assert status.untracked is True


def test_parse_status_porcelain_detached() -> None:
    status = _parse_status_porcelain("## HEAD (no branch)\n")
    assert status.detached is True
