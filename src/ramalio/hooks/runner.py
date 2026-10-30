"""Hook runner: sequential, deterministic capability lifecycle execution (E4-S1).

The runner invokes enabled capabilities for a lifecycle event in registry order
(INV-02/R13), wraps unexpected exceptions into a stable domain error (R16),
records successful, compensable actions in an in-memory journal (7.3) and runs
compensation in reverse order when an operation must be undone (R14).

Fail behavior (INV-03/INV-04):

* ``before_*`` failures are raised so the caller blocks the central operation
  and mutates nothing;
* ``after_*`` failures are raised too, but only after the runner has compensated
  the capability actions performed during this operation, so a partial state is
  never reported as full success.

The runner never runs Git; it only coordinates capability hooks.  Lifecycle
services call the central Git operation between ``before_*`` and ``after_*``.
"""

from __future__ import annotations

from ..capabilities.base import Capability, CapabilityContext
from ..capabilities.registry import CapabilityRegistry
from ..core.errors import CapabilityHookFailedError, RamalioError
from .events import (
    HookContext,
    HookJournal,
    HookJournalEntry,
    HookResult,
    LifecycleEvent,
)


class HookRunner:
    """Coordinate capability hooks for a lifecycle operation (7.1)."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._registry = registry

    def enabled(self, capability_context: CapabilityContext) -> tuple[Capability, ...]:
        """Return enabled capabilities in registry order (R13)."""

        return self._registry.enabled(capability_context)

    def run_event(
        self,
        event: LifecycleEvent,
        context: HookContext,
        *,
        journal: HookJournal,
        transaction=None,
    ) -> tuple[HookResult, ...]:
        """Run ``event`` across enabled capabilities sequentially (R2/R3/R13).

        Each capability's ``handle`` is invoked; a ``None`` result is treated as
        a no-op (R3).  Any exception is converted to
        :class:`CapabilityHookFailedError` (R16) and raised, so the caller
        decides how to react per phase.  Successful, compensable actions are
        journaled and, when a :class:`LifecycleTransaction` is provided, recorded
        as ownership-scoped, LIFO-compensable steps (E7-S0 R2/R4/R5).
        """

        results: list[HookResult] = []
        capabilities = self.enabled(context.capability_context)
        if event.is_teardown:
            # E6-S3 R13: tear resources down in reverse registration order so a
            # tunnel closes before its runtime and before the port is released.
            capabilities = tuple(reversed(capabilities))
        for capability in capabilities:
            try:
                result = self._invoke(capability, event, context)
            except CapabilityHookFailedError as exc:
                # Audit H4: a capability may have mutated a resource *before*
                # raising.  If the underlying error declares a (possible)
                # mutation, record a transaction step for it BEFORE propagating,
                # so rollback can compensate it (or classify it NOT_SAFE) rather
                # than losing the fact that it happened.
                self._record_partial_mutation(
                    capability, event, context, exc, transaction
                )
                raise
            if result is None:
                continue
            results.append(result)
            if result.success and result.changed:
                journal.record(
                    HookJournalEntry(
                        capability_name=capability.name,
                        event=event,
                        changed=result.changed,
                        compensation_available=result.compensation_available,
                    )
                )
                # E7-S0 R2: journal *every* mutation the operation performed,
                # even one without a safe compensation.  A compensable change
                # carries its compensation callback; a non-compensable change is
                # recorded with ``compensation=None`` so rollback classifies it
                # as ROLLBACK_NOT_SAFE and surfaces it in ``unsafe_resources``
                # instead of losing the fact that a resource was mutated.
                if transaction is not None:
                    cap = capability
                    ev = event.value
                    compensation = (
                        (lambda cap=cap, ev=ev: cap.compensate(ev, context))
                        if result.compensation_available
                        else None
                    )
                    transaction.record_step(
                        resource_type=f"capability:{cap.name}",
                        resource_identity=f"{context.operation}:{ev}",
                        action=ev,
                        owned=True,
                        compensation=compensation,
                    )
                    # Mark the step completed since the change already succeeded.
                    step_id = transaction.steps[-1].step_id
                    transaction.mark_completed(step_id)
            if not result.success:
                raise CapabilityHookFailedError(
                    f"capability '{capability.name}' failed during "
                    f"{event.value}: {result.summary}",
                    capability=capability.name,
                    event=event.value,
                )
        return tuple(results)

    def compensate(
        self, context: HookContext, *, journal: HookJournal
    ) -> list[str]:
        """Compensate journaled actions in reverse order (R14, INV-06).

        Returns the list of capabilities whose compensation could not be
        completed, so the caller can report a partial/degraded state rather than
        silently succeeding (INV-006).  Only actions performed by this operation
        are compensated (INV-06).
        """

        failures: list[str] = []
        for entry in journal.compensable_reversed():
            capability = self._registry.get(entry.capability_name)
            if capability is None:  # pragma: no cover - defensive
                failures.append(entry.capability_name)
                continue
            try:
                capability.compensate(entry.event.value, context)
            except Exception:  # noqa: BLE001 - compensation must not raise further
                failures.append(entry.capability_name)
        return failures

    # --- internals --------------------------------------------------------

    def _record_partial_mutation(
        self,
        capability: Capability,
        event: LifecycleEvent,
        context: HookContext,
        failure: CapabilityHookFailedError,
        transaction,
    ) -> None:
        """Record a transaction step for a mutation that happened before a hook
        raised (audit H4, E7-S0 R2).

        Reads the :class:`PartialMutationError` chained as the failure's cause.
        A step is recorded when the mutation is confirmed (``changed is True``)
        or UNKNOWN (``changed is None``) — i.e. whenever we cannot prove nothing
        was mutated.  ``changed is False`` records nothing.  A compensation is
        attached ONLY for a confirmed mutation that declares one available
        (``changed is True`` and ``compensation_available``); a changed-UNKNOWN
        step is recorded with no compensation so rollback classifies it
        ROLLBACK_NOT_SAFE and preserves the resource instead of running a blind
        compensation on ownership it cannot demonstrate (audit H1).
        """

        if transaction is None:
            return
        from ..core.errors import PartialMutationError

        cause = failure.__cause__
        if not isinstance(cause, PartialMutationError):
            return
        if cause.changed is False:
            # The operation proved it did not mutate before failing.
            return

        cap = capability
        ev = event.value
        # E7-S0 / audit H1: only a *confirmed* mutation (changed is True) may be
        # compensated, and only when a compensation is available.  A changed
        # UNKNOWN (None) means ownership cannot be demonstrated, so the step is
        # recorded WITHOUT a compensation: rollback then classifies it
        # ROLLBACK_NOT_SAFE and preserves the resource instead of running a
        # blind ``stop`` on something this operation may not own (INV-01/INV-03,
        # R11).
        if cause.changed is True and cause.compensation_available:
            compensation = lambda cap=cap, ev=ev: cap.compensate(ev, context)
        else:
            compensation = None
        identity = cause.resource_identity or f"{context.operation}:{ev}"
        transaction.record_step(
            resource_type=f"capability:{cap.name}",
            resource_identity=identity,
            action=f"{ev}:partial",
            owned=True,
            compensation=compensation,
        )
        # The mutation already happened (or may have): mark it completed so
        # rollback attempts its compensation / classifies it unsafe.
        transaction.mark_completed(transaction.steps[-1].step_id)

    def _invoke(
        self, capability: Capability, event: LifecycleEvent, context: HookContext
    ) -> HookResult | None:
        """Invoke one capability hook with an exception boundary (R16)."""

        try:
            raw = capability.handle(event.value, context)
        except RamalioError as exc:
            raise CapabilityHookFailedError(
                f"capability '{capability.name}' raised during {event.value}: {exc}",
                capability=capability.name,
                event=event.value,
            ) from exc
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            raise CapabilityHookFailedError(
                f"capability '{capability.name}' raised during {event.value}: "
                f"{type(exc).__name__}: {exc}",
                capability=capability.name,
                event=event.value,
            ) from exc

        if raw is None:
            return None
        if isinstance(raw, HookResult):
            return raw
        # A capability returned a non-standard value; treat as a no-op success
        # to keep the contract robust without inventing semantics.
        return HookResult(
            capability=capability.name,
            event=event,
            success=True,
            changed=False,
            summary="ok",
        )
