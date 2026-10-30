from __future__ import annotations

from pathlib import Path

from ramalio.git.repository import GitRepository
from ramalio.git.runner import GitCommandOutput, GitRunner

# Git subcommands that either contact a remote (R14) or mutate refs/worktrees
# (INV-03).  The boundary must never issue any of these in E2-S0.
_FORBIDDEN_SUBCOMMANDS = frozenset(
    {
        "fetch",
        "pull",
        "push",
        "remote",
        "clone",
        "commit",
        "merge",
        "rebase",
        "checkout",
        "switch",
        "reset",
        "branch",  # creating/deleting refs — only read-only queries are allowed
    }
)

# Mutating forms of `git worktree`.  `git worktree list` is read-only and fine.
_FORBIDDEN_WORKTREE_VERBS = frozenset({"add", "remove", "move", "prune", "lock", "unlock"})


class SpyRunner(GitRunner):
    """A runner that records every argv and delegates to a real Git run.

    Recording lets the test prove, on real repositories, that the boundary only
    ever issues read-only, local commands (AC-07, AC-08, CT-10).
    """

    def __init__(self, cwd: Path | str) -> None:
        super().__init__(cwd)
        self.calls: list[tuple[str, ...]] = []

    def run(
        self, *args: str, check: bool = False, cwd=None
    ) -> GitCommandOutput:
        self.calls.append(tuple(args))
        return super().run(*args, check=check, cwd=cwd)


def _assert_no_forbidden(calls: list[tuple[str, ...]]) -> None:
    for argv in calls:
        assert argv, "empty git invocation recorded"
        subcommand = argv[0]
        assert (
            subcommand not in _FORBIDDEN_SUBCOMMANDS
        ), f"forbidden git subcommand issued: {argv}"
        if subcommand == "worktree" and len(argv) > 1:
            assert (
                argv[1] not in _FORBIDDEN_WORKTREE_VERBS
            ), f"mutating worktree command issued: {argv}"


def test_full_observation_issues_only_readonly_commands(
    git_repo_with_commit: Path, run_git
) -> None:
    # CT-10 — exercise the whole boundary and prove no fetch/push/mutation ran.
    wt_path = git_repo_with_commit / ".local-wt" / "feature"
    run_git(
        git_repo_with_commit, "worktree", "add", "-b", "feature-x", str(wt_path)
    )

    spy = SpyRunner(git_repo_with_commit)
    repo = GitRepository(git_repo_with_commit, runner=spy)

    repo.ensure_valid()
    repo.resolve_base_branch("main")
    repo.branch_exists("feature-x")
    repo.resolve_ref("main")
    repo.list_worktrees()
    repo.get_worktree_by_path(wt_path)
    repo.get_worktree_by_branch("feature-x")
    repo.get_status()
    repo.get_status(wt_path)

    assert spy.calls, "expected the boundary to issue at least one git command"
    _assert_no_forbidden(spy.calls)
