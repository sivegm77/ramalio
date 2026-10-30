"""LifecycleTransaction: ownership-scoped steps with LIFO compensation (E7-S0).

The transaction is the common contract every mutable lifecycle operation uses to
record what it did and how to undo it safely.  It never performs a global
cleanup (INV-05/R15): it only compensates steps it was explicitly told this
operation owns, in reverse order (INV-02), preserving the original failure
(INV-04) and classifying the rollback outcome (R6).

The journal is in-memory (the operation is alive while it runs) but the design
does not preclude a durable journal later without changing callers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class RollbackOutcome(Enum):
    """Classification of a rollback attempt (R6)."""

    NONE = "NONE"  # nothing to roll back
    COMPLETE = "ROLLBACK_COMPLETE"
    PARTIAL = "ROLLBACK_PARTIAL"
    NOT_SAFE = "ROLLBACK_NOT_SAFE"


# A compensation undoes one step.  It must be idempotent (INV-06) and only ever
# act on the resource the step owns (INV-01).
Compensation = Callable[[], None]


@dataclass(slots=True)
class TransactionStep:
    """A recorded, potentially reversible mutation (R2)."""

    step_id: str
    resource_type: str
    resource_identity: str
    action: str
    owned: bool
    compensation: Compensation | None = None
    completed: bool = False

    @property
    def compensable(self) -> bool:
        return self.completed and self.owned and self.compensation is not None


@dataclass(frozen=True, slots=True)
class TransactionOutcome:
    """Result of a rolled-back transaction (R7).

    ``primary_error`` is the failure that triggered rollback; ``rollback_errors``
    are secondary failures encountered while compensating.  Together with
    ``outcome`` they let the CLI/status report a partial compensation (R16).
    """

    outcome: RollbackOutcome
    primary_error: BaseException | None
    rollback_errors: tuple[str, ...]
    unsafe_resources: tuple[str, ...]


class LifecycleTransaction:
    """Records ownership-scoped steps and compensates them in reverse (7).

    Usage::

        tx = LifecycleTransaction("init")
        tx.record_step("branch", identity, "create", owned=True,
                       compensation=undo_branch)
        ... perform the mutation ...
        tx.mark_completed(step_id)

    On failure the caller invokes :meth:`rollback`, which runs compensations
    LIFO and returns a :class:`TransactionOutcome`.
    """

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self._steps: list[TransactionStep] = []
        self._counter = 0

    def record_step(
        self,
        resource_type: str,
        resource_identity: str,
        action: str,
        *,
        owned: bool,
        compensation: Compensation | None = None,
    ) -> str:
        """Record a step before/around performing it (R2/R3)."""

        self._counter += 1
        step_id = f"{self.operation}-{self._counter}"
        self._steps.append(
            TransactionStep(
                step_id=step_id,
                resource_type=resource_type,
                resource_identity=resource_identity,
                action=action,
                owned=owned,
                compensation=compensation,
            )
        )
        return step_id

    def mark_completed(self, step_id: str) -> None:
        """Mark a recorded step as successfully completed (R2)."""

        for step in self._steps:
            if step.step_id == step_id:
                step.completed = True
                return
        raise KeyError(f"unknown transaction step: {step_id}")

    @property
    def steps(self) -> tuple[TransactionStep, ...]:
        return tuple(self._steps)

    def rollback(self, primary_error: BaseException | None) -> TransactionOutcome:
        """Compensate completed, owned steps in reverse order (R5, INV-02).

        Never touches steps that are not owned or not completed (INV-01/INV-03).
        A compensation that raises is recorded but does not abort the remaining
        compensations; the original ``primary_error`` is preserved (INV-04).
        """

        compensable = [s for s in reversed(self._steps) if s.compensable]
        # Steps that mutated but declared no safe compensation make the rollback
        # not fully safe.
        unsafe = [
            f"{s.resource_type}:{s.resource_identity}"
            for s in self._steps
            if s.completed and s.owned and s.compensation is None
        ]

        if not compensable and not unsafe:
            return TransactionOutcome(
                RollbackOutcome.NONE, primary_error, (), ()
            )

        rollback_errors: list[str] = []
        for step in compensable:
            try:
                assert step.compensation is not None
                step.compensation()
            except Exception as exc:  # noqa: BLE001 - rollback must continue
                rollback_errors.append(
                    f"{step.resource_type}:{step.resource_identity}: {exc}"
                )

        if rollback_errors:
            outcome = RollbackOutcome.PARTIAL
        elif unsafe:
            outcome = RollbackOutcome.NOT_SAFE
        else:
            outcome = RollbackOutcome.COMPLETE

        return TransactionOutcome(
            outcome=outcome,
            primary_error=primary_error,
            rollback_errors=tuple(rollback_errors),
            unsafe_resources=tuple(unsafe),
        )


def raise_if_unsafe(outcome: TransactionOutcome, *, operation: str) -> None:
    """Surface a partial/unsafe rollback in addition to the primary cause (E7-S0).

    Shared by every mutable lifecycle service: when ``outcome`` is
    ``ROLLBACK_PARTIAL`` or ``ROLLBACK_NOT_SAFE``, raises
    :class:`~ramalio.core.errors.LifecycleRollbackIncompleteError` instead
    of silently discarding the compensation result (R6/R7/R16).  A ``ROLLBACK_
    COMPLETE`` or ``ROLLBACK_NONE`` outcome is a no-op here; the caller re-raises
    the original failure on its own.
    """

    if outcome.outcome not in (RollbackOutcome.PARTIAL, RollbackOutcome.NOT_SAFE):
        return

    from ..core.errors import LifecycleRollbackIncompleteError

    cause_code = getattr(outcome.primary_error, "code", None)
    details = ", ".join(outcome.rollback_errors or outcome.unsafe_resources)
    raise LifecycleRollbackIncompleteError(
        f"rollback of '{operation}' could not fully compensate every mutated "
        f"resource ({outcome.outcome.value}); leftover: {details}",
        operation=operation,
        outcome=outcome.outcome.value,
        cause_code=cause_code,
        rollback_errors=outcome.rollback_errors,
        unsafe_resources=outcome.unsafe_resources,
    ) from outcome.primary_error
