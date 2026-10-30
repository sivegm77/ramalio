"""Structured Git domain models (E2-S0 R4, R5, R8, R13).

These value objects are the typed vocabulary the boundary returns.  They convert
Git's machine-readable output into stable structures so the rest of the product
never parses raw stdout (INV-02, R9).

Nothing here mutates Git or the filesystem; the models are pure observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BranchRef:
    """A local branch and the commit it currently points at (R4).

    ``commit`` is the resolved full object id.  ``BranchRef`` is only built for
    branches that exist; absence is represented by returning ``None`` from the
    query, never by an empty ref.
    """

    name: str
    commit: str


class CheckoutState(Enum):
    """Minimal checkout cleanliness classification for E2 safety (R8).

    E2-S0 only needs enough state to make safety decisions; a richer status
    model for UI belongs to E3 (7.4).  The states are not mutually exclusive in
    Git terms, so :class:`GitStatus` exposes independent booleans and derives a
    convenience summary from them.
    """

    CLEAN = "clean"
    DIRTY = "dirty"


@dataclass(frozen=True, slots=True)
class GitStatus:
    """Minimal, safety-oriented status of a checkout/worktree (R8).

    ``dirty`` means tracked files have staged or unstaged modifications.
    ``untracked`` means there are files Git does not track yet.  ``detached``
    means HEAD does not point at a branch.  These are independent facts derived
    from machine-readable Git output, never localized human text (7.4).
    """

    dirty: bool
    untracked: bool
    detached: bool

    @property
    def clean(self) -> bool:
        """Whether the checkout has no tracked modifications nor untracked files."""

        return not self.dirty and not self.untracked

    @property
    def state(self) -> CheckoutState:
        """Coarse cleanliness summary for callers that want a single value."""

        return CheckoutState.CLEAN if self.clean else CheckoutState.DIRTY


@dataclass(frozen=True, slots=True)
class WorktreeInfo:
    """A single worktree entry parsed from ``git worktree list --porcelain`` (R5).

    ``path`` is normalized to a canonical absolute path so comparisons across
    the product are reliable (INV-05).  ``branch`` is the short branch name when
    the worktree has one checked out, or ``None`` when it is detached.  ``head``
    is the resolved commit, absent only for a bare entry.
    """

    path: Path
    head: str | None
    branch: str | None
    bare: bool = False
    detached: bool = False
    locked: bool = False
    prunable: bool = False

    @property
    def is_detached(self) -> bool:
        """Whether the worktree has a detached HEAD (no branch checked out)."""

        return self.detached or (self.branch is None and not self.bare)
