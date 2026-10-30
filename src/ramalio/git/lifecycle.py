"""Mutating Git operations for lifecycle commands (E2-S1 7.3).

Everything in :mod:`.repository` is deliberately read-only and guarded by a
no-side-effects test.  Lifecycle commands such as ``init`` need to *create* and,
on failure, *retire* refs and worktrees.  Those mutations live here, in a
separate, explicit write boundary so the read-only contract of the query surface
stays intact (INV-03 applies to observation, not to lifecycle mutation).

Design choice (7.3): branch and worktree are created in a single atomic step via
``git worktree add -b <branch> <path> <base>``.  Git refuses to overwrite an
existing branch or a non-empty path, which reinforces the no-overwrite invariant
(INV-004 / R2 / R3 / R4) at the tool level.  Failures are wrapped as
:class:`GitCommandError` so callers get a stable domain error with the original
stderr preserved as an internal diagnostic cause (R16).

Rollback helpers (:meth:`remove_worktree`, :meth:`delete_branch`) only ever act
on resources the caller owns; ownership is decided by the caller's mutation
journal, never here (7.5, R5/R13).
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import GitCommandError
from .runner import GitRunner


class GitWriter:
    """Explicit write boundary for lifecycle mutations bound to one repo root.

    A dedicated :class:`GitRunner` is used (never the read-only repository's) so
    the two boundaries stay separable and independently testable.  A custom
    runner can be injected to simulate failures in unit tests.
    """

    def __init__(self, root: Path | str, *, runner: GitRunner | None = None) -> None:
        self._root = Path(root).resolve()
        self._runner = runner if runner is not None else GitRunner(self._root)

    @property
    def root(self) -> Path:
        return self._root

    # --- creation ---------------------------------------------------------

    def create_branch(self, *, branch: str, base: str) -> None:
        """Create ``branch`` pointing at ``base`` without checking it out (R6).

        Uses ``git branch <branch> <base>`` from the repository root.  Passing
        ``base`` explicitly makes the new branch start from the resolved base
        ref regardless of the invoking checkout's HEAD (R6), and creating it
        without checkout leaves the primary checkout untouched (R8).

        Git refuses when the branch already exists, so this fails closed instead
        of overwriting (INV-004).  Failures are wrapped as
        :class:`GitCommandError`.
        """

        self._runner.run("branch", branch, base, check=True, cwd=self._root)

    def add_worktree_for_branch(self, *, branch: str, worktree_path: Path) -> None:
        """Attach a worktree at ``worktree_path`` for an existing ``branch`` (R7).

        Uses ``git worktree add <path> <branch>`` (no ``-b``): the branch must
        already exist.  Git refuses a non-empty path, keeping the no-overwrite
        invariant (INV-004).  Failures are wrapped as :class:`GitCommandError`.
        """

        self._runner.run(
            "worktree",
            "add",
            str(worktree_path),
            branch,
            check=True,
            cwd=self._root,
        )

    def create_worktree_with_branch(
        self, *, branch: str, worktree_path: Path, base: str
    ) -> None:
        """Create ``branch`` from ``base`` and attach a worktree in one step.

        Convenience over ``git worktree add -b <branch> <path> <base>``.  Kept
        for callers that prefer the atomic form; :class:`~ramalio.core.
        init.InitWorkspaceService` uses the two-step form so rollback ownership
        is explicit and independently testable (7.3).  Failures are wrapped as
        :class:`GitCommandError`.
        """

        self._runner.run(
            "worktree",
            "add",
            "-b",
            branch,
            str(worktree_path),
            base,
            check=True,
            cwd=self._root,
        )

    # --- rollback helpers (owned resources only) --------------------------

    def remove_worktree(self, worktree_path: Path, *, force: bool = True) -> None:
        """Retire the worktree registered at ``worktree_path`` (R11).

        Intended for rollback of a worktree this operation created.  ``force``
        removes it even if the freshly-created checkout has content, since the
        caller owns the resource.  Failures are wrapped as
        :class:`GitCommandError`.
        """

        args = ["worktree", "remove"]
        if force:
            args.append("--force")
        args.append(str(worktree_path))
        self._runner.run(*args, check=True, cwd=self._root)

    def delete_branch(self, branch: str, *, force: bool = True) -> None:
        """Delete a local ``branch`` this operation created (R11).

        ``force`` (``git branch -D``) is used because a branch created moments
        ago for a worktree is not yet merged anywhere; the caller has already
        established ownership through its mutation journal before calling this
        (R5, R13).  Failures are wrapped as :class:`GitCommandError`.
        """

        flag = "-D" if force else "-d"
        self._runner.run("branch", flag, branch, check=True, cwd=self._root)

    def prune_worktrees(self) -> None:
        """Prune stale worktree administrative entries (best-effort rollback aid).

        Used after removing a worktree directory so Git's registry does not keep
        a dangling entry.  Never raises: pruning is a cleanup convenience and a
        failure here must not mask the original error.
        """

        try:
            self._runner.run("worktree", "prune", cwd=self._root)
        except GitCommandError:  # pragma: no cover - defensive best-effort cleanup
            pass
