"""Lifecycle locking helpers (E7-S1).

Provides a single place to acquire the per-target lifecycle lock that makes
mutable operations on the same target mutually exclusive (R3) while letting
distinct targets proceed in parallel (R4).  Read-only commands (list/status)
never call this (R15).
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from ..resources.locks import LockKey, LockManager, LockScope


@contextmanager
def target_lifecycle_lock(
    repository_root: Path,
    target: str,
    *,
    operation: str,
    lock_manager: LockManager | None = None,
    timeout: float | None = None,
):
    """Hold the target lifecycle lock for the duration of a mutable operation.

    A ``None`` ``lock_manager`` builds the default filesystem-backed manager for
    the repository.  The lock is released in ``finally`` even on exception (R12)
    and by the OS if the process dies (R11).
    """

    manager = (
        lock_manager
        if lock_manager is not None
        else LockManager.for_repository(repository_root)
    )
    key = LockKey(LockScope.TARGET, f"{repository_root}:{target}")
    with manager.acquire(key, operation=operation, timeout=timeout):
        yield
