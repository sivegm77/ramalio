"""Observable workspace model (E2-S0 R6, R7, R8).

This module bridges the derived identity from E1-S2
(:class:`~ramalio.core.naming.ResolvedWorkspaceIdentity`) with the
read-only Git boundary (:class:`~ramalio.git.repository.GitRepository`).

It answers a single question for a target: *what does Git currently observe for
this workspace?*  The answer is a pure observation
(:class:`ObservedWorkspace`): nothing is created, adopted or destroyed here
(INV-03, 7.6).  Lifecycle decisions (create / adopt / destroy) live in later
specs; this layer only reports facts and primitive precondition checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..git.models import GitStatus, WorktreeInfo
from ..git.repository import GitRepository
from .naming import ResolvedWorkspaceIdentity


@dataclass(frozen=True, slots=True)
class ObservedWorkspace:
    """A read-only snapshot of what Git observes for a resolved identity (R7).

    ``identity`` is the derived, non-persisted workspace identity.
    ``resolved_worktree_path`` is the identity's relative worktree path resolved
    against the repository root, so callers compare against a canonical absolute
    path (INV-05).  The remaining fields are facts observed from Git; none of
    them imply a decision.
    """

    identity: ResolvedWorkspaceIdentity
    resolved_worktree_path: Path
    branch_exists: bool
    worktree_exists: bool
    worktree: WorktreeInfo | None
    git_status: GitStatus | None

    @property
    def worktree_branch(self) -> str | None:
        """Branch checked out in the observed worktree, if any (R7)."""

        return self.worktree.branch if self.worktree is not None else None

    @property
    def worktree_head(self) -> str | None:
        """HEAD commit of the observed worktree, if any (R7)."""

        return self.worktree.head if self.worktree is not None else None

    @property
    def branch_checked_out_here(self) -> bool:
        """Whether the observed worktree has the identity's branch checked out."""

        return self.worktree_branch == self.identity.branch_name


class WorkspaceObserver:
    """Derives :class:`ObservedWorkspace` snapshots without mutating Git (R7, R8).

    A single observer wraps a :class:`GitRepository` and can observe any number
    of resolved identities.  Every method is read-only and free of network side
    effects (INV-03, R14).
    """

    def __init__(self, repository: GitRepository) -> None:
        self._repo = repository

    @property
    def repository(self) -> GitRepository:
        return self._repo

    def resolve_worktree_path(self, identity: ResolvedWorkspaceIdentity) -> Path:
        """Resolve the identity's relative worktree path against the repo root.

        E1-S2 derives ``worktree_path`` as a path relative to the repository
        root (a :class:`PurePosixPath`).  Here it becomes a canonical absolute
        path so it can be compared against Git-reported worktree paths (INV-05).
        """

        root = self._repo.get_root()
        combined = root / Path(*identity.worktree_path.parts)
        try:
            return combined.resolve()
        except OSError:  # pragma: no cover - defensive
            return combined.absolute()

    def observe(self, identity: ResolvedWorkspaceIdentity) -> ObservedWorkspace:
        """Observe the current Git state for ``identity`` (R7).

        The observation is a snapshot of facts.  ``git_status`` is only computed
        when a worktree actually exists on disk, since there is no checkout to
        inspect otherwise (R8).
        """

        resolved_path = self.resolve_worktree_path(identity)
        branch_exists = self._repo.branch_exists(identity.branch_name)

        worktree = self._repo.get_worktree_by_path(resolved_path)
        worktree_exists = worktree is not None or resolved_path.exists()

        git_status: GitStatus | None = None
        if worktree is not None and worktree.path.exists():
            git_status = self._repo.get_status(worktree.path)

        return ObservedWorkspace(
            identity=identity,
            resolved_worktree_path=resolved_path,
            branch_exists=branch_exists,
            worktree_exists=worktree_exists,
            worktree=worktree,
            git_status=git_status,
        )

    # --- primitive precondition facts (no decisions) ----------------------

    def branch_collision(self, identity: ResolvedWorkspaceIdentity) -> bool:
        """Whether the derived branch already exists (R9).

        Reports the fact only; whether that branch is adoptable is decided by
        later specs (7.6).
        """

        return self._repo.branch_exists(identity.branch_name)

    def worktree_path_registered(
        self, identity: ResolvedWorkspaceIdentity
    ) -> WorktreeInfo | None:
        """Return the worktree registered at the derived path, if any (R10)."""

        return self._repo.get_worktree_by_path(
            self.resolve_worktree_path(identity)
        )

    def worktree_path_exists(self, identity: ResolvedWorkspaceIdentity) -> bool:
        """Whether the derived worktree path already exists on disk (R10)."""

        return self.resolve_worktree_path(identity).exists()

    def branch_used_by_other_worktree(
        self, identity: ResolvedWorkspaceIdentity
    ) -> WorktreeInfo | None:
        """Return the worktree using the derived branch, if different path (R11).

        Distinguishes the target branch being checked out in *another* worktree
        from it being checked out at the identity's own path.  Returns ``None``
        when the branch is unused or only used at the identity's own location.
        """

        worktree = self._repo.get_worktree_by_branch(identity.branch_name)
        if worktree is None:
            return None
        if worktree.path == self.resolve_worktree_path(identity):
            return None
        return worktree
