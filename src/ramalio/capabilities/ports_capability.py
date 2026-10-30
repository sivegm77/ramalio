"""Ports capability: bind the port resource to the lifecycle (E6-S1).

Wraps the :mod:`ramalio.resources.ports` allocator as an E4 capability so
port reservation participates in init/destroy/status/doctor without the core
knowing about ports.  Enabled from the top-level ``[ports]`` section (not
``[capabilities.*]``), because ports is a managed resource rather than a
tool-style capability.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..core.errors import RamalioError
from ..core.naming import ResolvedWorkspaceIdentity
from ..resources.ports import PortAllocator, PortReservationStore
from .base import (
    BaseCapability,
    CapabilityContext,
    CapabilityDoctorCheck,
    CapabilityState,
    CapabilityStatus,
    DoctorCheckStatus,
)

CAPABILITY_NAME = "ports"

_AFTER_INIT = "after_init"
_AFTER_START = "after_start"
_BEFORE_DESTROY = "before_destroy"


class PortsCapability(BaseCapability):
    """Allocate/release a per-target port around the lifecycle (E6-S1)."""

    capability_name = CAPABILITY_NAME

    def __init__(
        self,
        *,
        store_base: Path | None = None,
        port_probe=None,
        lock_manager=None,
    ) -> None:
        self._store_base = store_base
        self._port_probe = port_probe
        self._lock_manager = lock_manager

    def is_enabled(self, context: CapabilityContext) -> bool:
        return context.config.ports.enabled

    def _allocator(self, context: CapabilityContext) -> PortAllocator:
        store = PortReservationStore(
            context.config.repository_root, base=self._store_base
        )
        kwargs = {}
        if self._port_probe is not None:
            kwargs["port_probe"] = self._port_probe
        # E7-S1 R5: protect the port pool with a cross-process lock so two
        # concurrent targets never pick the same port.  Build the default
        # filesystem-backed manager for this repository unless one was injected
        # (tests may inject a shared manager to exercise real contention).
        lock_manager = self._lock_manager
        if lock_manager is None:
            from ..resources.locks import LockManager

            # Keep lock state co-located with the reservation store base so
            # tests that redirect the store (store_base) stay hermetic and do
            # not touch the user's real state directory.
            lock_manager = LockManager.for_repository(
                context.config.repository_root, base=self._store_base
            )
        return PortAllocator(
            context.config.ports, store, lock_manager=lock_manager, **kwargs
        )

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "ports disabled"
            )
        identity = context.identity
        if identity is None:
            return CapabilityStatus(
                self.name, CapabilityState.UNKNOWN, "no target in context"
            )
        reservation = self._allocator(context).current(identity.target.value)
        if reservation is None:
            return CapabilityStatus(
                self.name, CapabilityState.STOPPED, "no port reserved"
            )
        return CapabilityStatus(
            self.name, CapabilityState.ACTIVE, f"port {reservation.port} reserved"
        )

    # --- doctor -----------------------------------------------------------

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        if not self.is_enabled(context):
            return ()
        cfg = context.config.ports
        # Config validation already enforces the range; report it here (R9).
        return (
            CapabilityDoctorCheck(
                check_id="PORTS_RANGE",
                status=DoctorCheckStatus.PASS,
                summary=(
                    f"port range {cfg.start}..{cfg.start + cfg.size - 1} configured"
                ),
            ),
        )

    # --- lifecycle hooks --------------------------------------------------

    def handle(self, event: str, context: object) -> object:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return None
        identity: ResolvedWorkspaceIdentity | None = cap_ctx.identity
        if identity is None:
            return None

        changed = False
        if event in (_AFTER_INIT, _AFTER_START):
            # E7-S0 R3/R11 (P5): ownership must reflect what THIS call actually
            # reserved, not just that a reservation exists afterward.  A
            # reservation that already existed (from init, from `adopt` +
            # a later start, or left over from an earlier partial run) is not
            # owned by this call and must never be released on rollback.
            # Idempotent: reuse an existing reservation rather than
            # reallocating.
            allocator = self._allocator(cap_ctx)
            existing = allocator.current(identity.target.value)
            allocator.reserve(identity.target.value)
            changed = existing is None
        elif event == _BEFORE_DESTROY:
            # R10/R12: release only this target's reservation.
            changed = self._allocator(cap_ctx).release(identity.target.value)
        else:
            return None

        from ..hooks import HookResult, LifecycleEvent

        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary=f"ports {event}",
            compensation_available=changed and event in (_AFTER_INIT, _AFTER_START),
        )

    def compensate(self, event: str, context: object) -> None:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return
        identity = cap_ctx.identity
        if identity is None or event not in (_AFTER_INIT, _AFTER_START):
            return
        # E7-S0 R6/R7 (P4): let a failure propagate to
        # LifecycleTransaction.rollback(), which records it as a
        # rollback_error instead of silently reporting ROLLBACK_COMPLETE.
        self._allocator(cap_ctx).release(identity.target.value)
