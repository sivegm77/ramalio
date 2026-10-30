"""Common lifecycle transaction and rollback contract (E7-S0).

Replaces ad-hoc, per-command rollback with a shared mechanism: a
:class:`LifecycleTransaction` records ownership-scoped steps, compensates them
in reverse (LIFO) order on failure, composes the primary error with rollback
errors, and classifies the outcome as complete / partial / not-safe.
"""

from __future__ import annotations

from .transaction import (
    LifecycleTransaction,
    RollbackOutcome,
    TransactionOutcome,
    TransactionStep,
    raise_if_unsafe,
)

__all__ = [
    "LifecycleTransaction",
    "RollbackOutcome",
    "TransactionOutcome",
    "TransactionStep",
    "raise_if_unsafe",
]
