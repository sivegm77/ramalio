"""Git boundary for ramalio (E2-S0).

This package is the single technical boundary around Git (INV-02).  The rest of
the product must query branches, worktrees and checkout status through the
abstractions exposed here instead of shelling out to Git directly or parsing raw
stdout.

E2-S0 is strictly read-only: it inspects and models Git state but never creates
or removes refs or worktrees (INV-03) and never contacts a remote (R14).
"""

from __future__ import annotations

from .models import (
    BranchRef,
    GitStatus,
    WorktreeInfo,
)
from .repository import GitRepository
from .runner import GitCommandOutput, GitRunner

__all__ = [
    "BranchRef",
    "GitStatus",
    "WorktreeInfo",
    "GitRepository",
    "GitCommandOutput",
    "GitRunner",
]
