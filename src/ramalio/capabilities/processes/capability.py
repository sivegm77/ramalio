"""The generic managed-processes capability (E4-S2).

This is the product's first real capability.  It coordinates project-declared
processes bound unambiguously to a target through the E4-S0/E4-S1 contracts,
never adding process concepts to the core (INV-04).  It requires neither tmux
nor Docker (R24/INV-07 of E5/E6 scope).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ...core.errors import (
    RamalioError,
    ProcessOwnershipMismatchError,
    ProcessStartRollbackIncompleteError,
)
from ...core.naming import ResolvedWorkspaceIdentity
from ..base import (
    BaseCapability,
    CapabilityContext,
    CapabilityDoctorCheck,
    CapabilityState,
    CapabilityStatus,
    DoctorCheckStatus,
)
from .models import ProcessItem, ProcessState, ProcessStatus, parse_process_items
from .runtime import (
    ProcessInspector,
    ProcessLauncher,
    ProcessMetadata,
    ProcessMetadataStore,
    ProcessTerminator,
    _pid_alive,
)

CAPABILITY_NAME = "processes"

# Lifecycle events (mirrors hooks.LifecycleEvent values; kept as strings to
# avoid importing the hooks package into a capability).
_AFTER_INIT = "after_init"
_AFTER_START = "after_start"
_BEFORE_STOP = "before_stop"
_BEFORE_DESTROY = "before_destroy"


class ProcessesCapability(BaseCapability):
    """Manage per-target processes (E4-S2)."""

    capability_name = CAPABILITY_NAME

    def __init__(
        self,
        *,
        metadata_base: Path | None = None,
        inspector: ProcessInspector | None = None,
        terminator: ProcessTerminator | None = None,
    ) -> None:
        self._metadata_base = metadata_base
        self._inspector = inspector or ProcessInspector()
        self._terminator = terminator or ProcessTerminator(self._inspector)
        # E7-S0 R3/R11 (P3): remembers exactly which items THIS call started, per
        # (target, event), so compensate() stops only those and never a
        # preexisting process that merely shares the same `start_on_*` flag.
        # Scoped narrowly and cleared immediately after use.
        self._started_by_call: dict[tuple[str, str], list[ProcessItem]] = {}

    # --- config -----------------------------------------------------------

    def _items(self, context: CapabilityContext) -> tuple[ProcessItem, ...]:
        entry = context.capability_config(self.name)
        if entry is None:
            return ()
        return parse_process_items(entry.options)

    def validate_config(self, context: CapabilityContext) -> None:
        # Parsing performs full structural validation and duplicate detection.
        self._items(context)

    # --- helpers ----------------------------------------------------------

    def _store(self, context: CapabilityContext, target: str) -> ProcessMetadataStore:
        return ProcessMetadataStore(
            context.config.repository_root, target, base=self._metadata_base
        )

    def _worktree_path(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> Path:
        root = context.config.repository_root
        return (root / Path(*identity.worktree_path.parts)).resolve()

    def _target(self, context: CapabilityContext) -> str | None:
        return context.identity.target.value if context.identity else None

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "capability disabled"
            )
        target = self._target(context)
        if target is None:
            return CapabilityStatus(
                self.name, CapabilityState.UNKNOWN, "no target in context"
            )

        try:
            per_item = self.item_statuses(context)
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "process config invalid", str(exc)
            )

        return CapabilityStatus(
            name=self.name,
            state=self._aggregate(per_item),
            summary=self._summary(per_item),
        )

    def item_statuses(self, context: CapabilityContext) -> tuple[ProcessStatus, ...]:
        """Return the observed status of each process item (R13, R22)."""

        target = self._target(context)
        assert target is not None
        store = self._store(context, target)
        statuses: list[ProcessStatus] = []
        for item in self._items(context):
            metadata = store.load(item.name)
            statuses.append(self._item_status(item, metadata))
        return tuple(statuses)

    def _item_status(
        self, item: ProcessItem, metadata: ProcessMetadata | None
    ) -> ProcessStatus:
        if metadata is None:
            return ProcessStatus(item.name, ProcessState.STOPPED, None, "stopped")
        if self._inspector.owns(metadata):
            return ProcessStatus(
                item.name, ProcessState.ACTIVE, metadata.pid, "active"
            )
        # Metadata exists but no owned process corresponds -> stale (R13).
        return ProcessStatus(
            item.name, ProcessState.STALE, metadata.pid, "stale metadata"
        )

    def _aggregate(self, statuses: Sequence[ProcessStatus]) -> CapabilityState:
        if not statuses:
            return CapabilityState.READY
        states = {s.state for s in statuses}
        if states == {ProcessState.ACTIVE}:
            return CapabilityState.ACTIVE
        if states == {ProcessState.STOPPED}:
            return CapabilityState.STOPPED
        if ProcessState.ERROR in states:
            return CapabilityState.ERROR
        if ProcessState.STALE in states:
            return CapabilityState.DEGRADED
        # A valid mix of ACTIVE and STOPPED.
        return CapabilityState.DEGRADED

    def _summary(self, statuses: Sequence[ProcessStatus]) -> str:
        if not statuses:
            return "no processes declared"
        parts = [f"{s.name}={s.state.value}" for s in statuses]
        return ", ".join(parts)

    # --- doctor -----------------------------------------------------------

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        if not self.is_enabled(context):
            return ()
        try:
            items = self._items(context)
        except RamalioError as exc:
            return (
                CapabilityDoctorCheck(
                    check_id="PROCESSES_CONFIG",
                    status=DoctorCheckStatus.FAIL,
                    summary="processes configuration is invalid",
                    details=str(exc),
                ),
            )

        checks: list[CapabilityDoctorCheck] = []
        import shutil

        for item in items:
            exe = item.command[0]
            available = (
                shutil.which(exe) is not None or Path(exe).exists()
            )
            checks.append(
                CapabilityDoctorCheck(
                    check_id=f"PROCESS_{item.name.upper()}_COMMAND",
                    status=(
                        DoctorCheckStatus.PASS
                        if available
                        else DoctorCheckStatus.WARN
                    ),
                    summary=(
                        f"command '{exe}' available"
                        if available
                        else f"command '{exe}' not found on PATH"
                    ),
                    remediation=None
                    if available
                    else f"Ensure '{exe}' is installed and on PATH.",
                )
            )
        return tuple(checks)

    # --- lifecycle hooks --------------------------------------------------

    def handle(self, event: str, context: object) -> object:
        """Dispatch lifecycle events to process start/stop (E4-S1 R2, 7.4).

        ``context`` is a ``HookContext``; its ``capability_context`` carries the
        resolved config + identity.  Returns a ``HookResult`` describing whether
        the capability changed state so the hook journal can compensate across
        capabilities (E4-S1 R8/R14); returns ``None`` for unrelated events.
        """

        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return None
        identity = cap_ctx.identity
        if identity is None:
            return None

        items = self._items(cap_ctx)
        changed = 0
        target = identity.target.value
        if event == _AFTER_INIT:
            started = self._start_items(
                cap_ctx, identity, [i for i in items if i.start_on_init]
            )
            self._started_by_call[(target, event)] = started
            changed = len(started)
        elif event == _AFTER_START:
            started = self._start_items(
                cap_ctx, identity, [i for i in items if i.start_on_start]
            )
            self._started_by_call[(target, event)] = started
            changed = len(started)
        elif event == _BEFORE_STOP:
            changed = self._stop_items(
                cap_ctx, identity, [i for i in items if i.stop_on_stop]
            )
        elif event == _BEFORE_DESTROY:
            changed = self._stop_items(
                cap_ctx,
                identity,
                [i for i in items if i.stop_on_destroy],
                required=True,
            )
        else:
            return None

        from ...hooks import HookResult, LifecycleEvent

        started_event = event in (_AFTER_INIT, _AFTER_START)
        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed > 0,
            summary=f"{changed} process(es) affected",
            # Only 'start' actions are compensable by stopping them again.
            compensation_available=started_event and changed > 0,
        )

    def _start_items(
        self,
        context: CapabilityContext,
        identity: ResolvedWorkspaceIdentity,
        items: list[ProcessItem],
    ) -> list[ProcessItem]:
        """Start ``items``, compensating started ones on partial failure (7.5).

        Returns exactly the items newly started by THIS call (never one that
        was already active and thus not owned by this call, E7-S0 R3/R11).
        """

        store = self._store(context, identity.target.value)
        worktree = self._worktree_path(context, identity)
        launcher = ProcessLauncher(worktree)
        started: list[ProcessItem] = []
        try:
            for item in items:
                existing = store.load(item.name)
                if existing is not None and self._inspector.owns(existing):
                    # R9: already active -> do not duplicate.
                    continue
                metadata = launcher.launch(item)
                metadata = ProcessMetadata(
                    target=identity.target.value,
                    process_name=item.name,
                    pid=metadata.pid,
                    start_time=metadata.start_time,
                    cwd=metadata.cwd,
                )
                store.save(metadata)
                started.append(item)
        except Exception as exc:
            # Compensation: stop only what this operation started, reverse
            # order.  A cleanup failure must not silently mask the original
            # launch failure (E7-S0 R6/R7, P4) and must stay STRUCTURALLY
            # diagnosable (audit H8): collect per-item cleanup errors and the
            # processes left running, then raise a dedicated rollback-incomplete
            # error that mirrors the LifecycleTransaction outcome semantics.
            cleanup_errors: list[str] = []
            leftover: list[str] = []
            for item in reversed(started):
                metadata = store.load(item.name)
                if metadata is not None:
                    try:
                        self._terminator.terminate(
                            metadata, timeout=item.stop_timeout
                        )
                        store.delete(item.name)
                    except RamalioError as cleanup_exc:
                        cleanup_errors.append(f"{item.name}: {cleanup_exc}")
                        leftover.append(item.name)
            if cleanup_errors:
                raise ProcessStartRollbackIncompleteError(
                    f"process start failed ({exc}); additionally failed to stop "
                    f"already-started items: {', '.join(cleanup_errors)}",
                    primary_error=exc,
                    cleanup_errors=tuple(cleanup_errors),
                    leftover_processes=tuple(leftover),
                ) from exc
            raise
        return started

    def _stop_items(
        self,
        context: CapabilityContext,
        identity: ResolvedWorkspaceIdentity,
        items: list[ProcessItem],
        *,
        required: bool = False,
    ) -> int:
        """Stop ``items`` owned by this target (R10, R11, R18).

        When ``required`` (before_destroy), an ownership mismatch that prevents
        safe termination is raised so destroy blocks (R18); otherwise a stale
        entry is simply cleaned up.  Returns the number of processes stopped.
        """

        store = self._store(context, identity.target.value)
        stopped = 0
        for item in items:
            metadata = store.load(item.name)
            if metadata is None:
                continue
            if not self._inspector.owns(metadata):
                # Distinguish a dead process (safe to clean up as stale) from a
                # live PID we can no longer verify (PID reuse). For a required
                # stop (before_destroy), an unverifiable live PID blocks (R11/R18).
                if required and _pid_alive(metadata.pid):
                    raise ProcessOwnershipMismatchError(
                        f"process '{item.name}' (pid {metadata.pid}) cannot be "
                        "verified as owned; destroy is blocked to avoid signaling "
                        "the wrong process"
                    )
                store.delete(item.name)
                continue
            try:
                self._terminator.terminate(metadata, timeout=item.stop_timeout)
            except ProcessOwnershipMismatchError:
                if required:
                    raise
                continue
            store.delete(item.name)
            stopped += 1
        return stopped

    def compensate(self, event: str, context: object) -> None:
        """Undo processes started during ``event`` by stopping them (E4-S1 R6).

        Only start events are compensable.  Stops exactly the items THIS call
        started (E7-S0 R3/R11, P3): recomputing from configuration would also
        target a process that was already running before this call and is
        therefore not owned by it.
        """

        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return
        identity = cap_ctx.identity
        if identity is None:
            return
        if event not in (_AFTER_INIT, _AFTER_START):
            return
        target = identity.target.value
        targets = self._started_by_call.pop((target, event), None)
        if not targets:
            return
        # E7-S0 R6/R7 (P4): let a failure propagate so
        # LifecycleTransaction.rollback() records it as a rollback_error
        # instead of silently reporting ROLLBACK_COMPLETE.
        self._stop_items(cap_ctx, identity, targets)
