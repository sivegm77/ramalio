"""HookRunner ↔ LifecycleTransaction journaling semantics (E7-S0).

These unit tests target the runner/transaction wiring directly (no Git), proving
that EVERY mutation a capability performs is recorded in the transaction — even
a mutation that declares no safe compensation — so rollback can classify the
outcome as ROLLBACK_NOT_SAFE and surface the mutated resource in
``unsafe_resources`` (E7-S0 R2/R6/R7), instead of silently losing it.
"""

from __future__ import annotations

import pytest

from ramalio.capabilities import BaseCapability, CapabilityRegistry
from ramalio.capabilities.base import CapabilityContext
from ramalio.core.errors import CapabilityHookFailedError
from ramalio.hooks import HookContext, HookJournal, HookResult, LifecycleEvent
from ramalio.hooks.runner import HookRunner
from ramalio.transactions import LifecycleTransaction
from ramalio.transactions.transaction import RollbackOutcome


class _Cap(BaseCapability):
    """Fake capability with configurable change/compensation/failure behavior."""

    def __init__(
        self,
        name: str,
        *,
        changed: bool = True,
        compensation_available: bool = True,
        fail: bool = False,
        log: list[str] | None = None,
    ) -> None:
        self.capability_name = name
        self._changed = changed
        self._comp = compensation_available
        self._fail = fail
        self._log = log if log is not None else []

    def is_enabled(self, context) -> bool:
        return True

    def handle(self, event: str, context: object) -> object:
        if self._fail:
            raise RuntimeError(f"{self.capability_name} boom on {event}")
        self._log.append(f"{self.capability_name}:{event}")
        return HookResult(
            capability=self.capability_name,
            event=LifecycleEvent(event),
            success=True,
            changed=self._changed,
            summary="ok",
            compensation_available=self._changed and self._comp,
        )

    def compensate(self, event: str, context: object) -> None:
        self._log.append(f"{self.capability_name}:compensate:{event}")


def _ctx() -> HookContext:
    # Config/identity are unused by these fakes; a bare context is enough.
    return HookContext(
        capability_context=CapabilityContext(config=None, identity=None),
        operation="start",
    )


def test_non_compensable_mutation_is_journaled_as_unsafe() -> None:
    log: list[str] = []
    # A mutates and declares NO safe compensation; B fails afterwards.
    cap_a = _Cap("a", changed=True, compensation_available=False, log=log)
    cap_b = _Cap("b", fail=True, log=log)
    registry = CapabilityRegistry.with_capabilities([cap_a, cap_b])
    runner = HookRunner(registry)
    tx = LifecycleTransaction("start")
    ctx = _ctx()

    with pytest.raises(CapabilityHookFailedError):
        runner.run_event(
            LifecycleEvent.AFTER_START, ctx, journal=HookJournal(), transaction=tx
        )

    outcome = tx.rollback(primary_error=RuntimeError("b failed"))
    # A's mutation must be recorded even without compensation -> NOT_SAFE.
    assert outcome.outcome is RollbackOutcome.NOT_SAFE
    assert any("capability:a" in r for r in outcome.unsafe_resources)
    # A was not "compensated" because it declared none.
    assert "a:compensate:after_start" not in log


def test_compensable_mutation_is_rolled_back() -> None:
    log: list[str] = []
    cap_a = _Cap("a", changed=True, compensation_available=True, log=log)
    cap_b = _Cap("b", fail=True, log=log)
    registry = CapabilityRegistry.with_capabilities([cap_a, cap_b])
    runner = HookRunner(registry)
    tx = LifecycleTransaction("start")

    with pytest.raises(CapabilityHookFailedError):
        runner.run_event(
            LifecycleEvent.AFTER_START, _ctx(), journal=HookJournal(), transaction=tx
        )

    outcome = tx.rollback(primary_error=RuntimeError("b failed"))
    assert outcome.outcome is RollbackOutcome.COMPLETE
    assert "a:compensate:after_start" in log


def test_mixed_compensation_yields_partial_or_not_safe() -> None:
    # A compensable, C non-compensable, B fails between/after: the presence of a
    # non-compensable owned mutation makes the rollback NOT_SAFE overall while
    # still compensating what it can.
    log: list[str] = []
    cap_a = _Cap("a", changed=True, compensation_available=True, log=log)
    cap_c = _Cap("c", changed=True, compensation_available=False, log=log)
    cap_b = _Cap("b", fail=True, log=log)
    registry = CapabilityRegistry.with_capabilities([cap_a, cap_c, cap_b])
    runner = HookRunner(registry)
    tx = LifecycleTransaction("start")

    with pytest.raises(CapabilityHookFailedError):
        runner.run_event(
            LifecycleEvent.AFTER_START, _ctx(), journal=HookJournal(), transaction=tx
        )

    outcome = tx.rollback(primary_error=RuntimeError("b failed"))
    assert outcome.outcome is RollbackOutcome.NOT_SAFE
    assert any("capability:c" in r for r in outcome.unsafe_resources)
    # The compensable one still got compensated (LIFO, best effort).
    assert "a:compensate:after_start" in log
