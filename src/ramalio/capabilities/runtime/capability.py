"""Runtime capability wrapping an optional per-target runtime driver (E6-S0).

The capability resolves a driver by name from ``[capabilities.runtime].driver``
(default ``none``) and coordinates it through the E4 hooks, without redefining
the lifecycle.  The core works without any runtime (INV): the ``none`` driver is
the base behavior.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ...core.errors import (
    RamalioError,
    RuntimeCleanupFailedError,
    RuntimeDriverUnknownError,
    RuntimeStartFailedError,
    RuntimeStopFailedError,
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
from .base import RuntimeDriver, RuntimeResult, RuntimeState, RuntimeWorkspace
from .none_driver import DRIVER_NAME as NONE_DRIVER, NoneRuntimeDriver

CAPABILITY_NAME = "runtime"

_AFTER_INIT = "after_init"
_AFTER_ADOPT = "after_adopt"
_AFTER_START = "after_start"
_BEFORE_STOP = "before_stop"
_BEFORE_DESTROY = "before_destroy"

# Registry of driver factories by name (explicit, extensible; E6-S2 registers
# the Docker Compose driver here). A factory receives the runtime capability's
# namespaced options and, optionally, a DriverBuildContext carrying the real
# project name and a per-target port provider so drivers can honor project+target
# identity (E6-S2 R3) and inject the reserved port (E6-S2 R9) without the core
# knowing any driver specifics.


@dataclass(frozen=True, slots=True)
class DriverBuildContext:
    """Build-time context passed to a runtime driver factory (E6-S2 R3/R9).

    ``project_name`` is the real ``[project].name`` so the driver derives a
    unique ``{project}-{target}`` identity.  ``port_provider`` maps a
    ``RuntimeWorkspace`` to the E6-S1 reserved port (or ``None``) so a driver can
    inject it as explicit, non-secret runtime configuration.  ``repository_root``
    and ``worktree_directory`` let a driver run target-less diagnostics (audit
    H6): ``doctor`` normally has no target, so the driver still needs the repo
    root to locate the configured compose file.
    """

    project_name: str
    port_provider: Callable[[object], int | None] | None
    repository_root: Path | None = None
    worktree_directory: str | None = None


DriverFactory = Callable[..., RuntimeDriver]

_DRIVERS: dict[str, DriverFactory] = {
    NONE_DRIVER: lambda _options, _context=None: NoneRuntimeDriver(),
}


def register_driver(name: str, factory: DriverFactory) -> None:
    """Register a runtime driver factory by name (extension seam for E6-S2)."""

    _DRIVERS[name] = factory


def _runtime_to_capability_state(state: RuntimeState) -> CapabilityState:
    return {
        RuntimeState.NOT_APPLICABLE: CapabilityState.READY,
        RuntimeState.STOPPED: CapabilityState.STOPPED,
        RuntimeState.STARTING: CapabilityState.ACTIVE,
        RuntimeState.RUNNING: CapabilityState.ACTIVE,
        RuntimeState.DEGRADED: CapabilityState.DEGRADED,
        RuntimeState.FAILED: CapabilityState.ERROR,
        RuntimeState.UNKNOWN: CapabilityState.UNKNOWN,
    }[state]


class RuntimeCapability(BaseCapability):
    """Coordinate an optional runtime driver per target (E6-S0)."""

    capability_name = CAPABILITY_NAME

    def __init__(self, *, drivers: dict[str, DriverFactory] | None = None) -> None:
        self._drivers = drivers if drivers is not None else _DRIVERS

    # A runtime capability is considered enabled whenever a runtime section is
    # present; the 'none' driver is the safe default when unset (R1).
    def is_enabled(self, context: CapabilityContext) -> bool:
        return context.capability_config(self.name) is not None

    def _driver_name(self, context: CapabilityContext) -> str:
        entry = context.capability_config(self.name)
        if entry is None:
            return NONE_DRIVER
        return str(entry.options.get("driver", NONE_DRIVER))

    def _driver(self, context: CapabilityContext) -> RuntimeDriver:
        name = self._driver_name(context)
        factory = self._drivers.get(name)
        if factory is None:
            raise RuntimeDriverUnknownError(
                f"runtime driver '{name}' is not registered"
            )
        entry = context.capability_config(self.name)
        options = dict(entry.options) if entry is not None else {}
        build_context = self._build_context(context)
        # Backward-compatible call: factories may accept just options or also a
        # DriverBuildContext (E6-S2 wiring). Inspect the signature so both forms
        # keep working without the core knowing driver specifics.
        try:
            params = inspect.signature(factory).parameters
        except (TypeError, ValueError):  # pragma: no cover - builtins
            params = {}
        if len(params) >= 2:
            return factory(options, build_context)
        return factory(options)

    def _build_context(self, context: CapabilityContext) -> DriverBuildContext:
        """Assemble the driver build context: project name + port provider (R3/R9).

        The port provider resolves the E6-S1 reservation for the workspace's
        target from the project-namespaced store, so the reserved port reaches
        the runtime as explicit configuration without hardcoding any project's
        variable name (R9/AC-08).
        """

        project_name = context.config.project.name

        def port_provider(workspace: object) -> int | None:
            if not context.config.ports.enabled:
                return None
            target = getattr(workspace, "target", None)
            if target is None:
                return None
            from ...resources.ports import PortReservationStore

            store = PortReservationStore(context.config.repository_root)
            reservation = store.load(target)
            return reservation.port if reservation is not None else None

        return DriverBuildContext(
            project_name=project_name,
            port_provider=port_provider,
            repository_root=context.config.repository_root,
            worktree_directory=context.config.worktree.directory,
        )

    def validate_config(self, context: CapabilityContext) -> None:
        # Resolving the driver validates the configured name (R7).
        self._driver(context)

    # --- downstream provider seam (E10-S1 R2 / E10-S2 / E10-S3) -----------

    def resolve_command_executor(self, context: CapabilityContext):
        """Return the active driver as a ``RuntimeCommandExecutor`` or ``None``.

        Downstream providers (bootstrap ``executor="runtime"``, Postgres data)
        depend on the :class:`RuntimeCommandExecutor` protocol, not on any
        concrete driver.  This resolves the configured driver and returns it
        only when it actually implements that protocol; otherwise ``None`` so the
        caller can fail config/doctor before mutating (E10-S1 R2, E10-S2 R4,
        E10-S3 R2).  Never imports Docker Compose here.
        """

        from .base import RuntimeCommandExecutor

        driver = self._driver(context)
        if isinstance(driver, RuntimeCommandExecutor):
            return driver
        return None

    def workspace_for(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> RuntimeWorkspace:
        """Build the :class:`RuntimeWorkspace` for a target (downstream seam)."""

        return self._workspace(context, identity)

    def _workspace(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> RuntimeWorkspace:
        root = context.config.repository_root
        worktree = (root / Path(*identity.worktree_path.parts)).resolve()
        return RuntimeWorkspace(
            target=identity.target.value,
            worktree_path=worktree,
            identity=identity,
            repository_root=root,
        )

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "no runtime configured"
            )
        identity = context.identity
        try:
            driver = self._driver(context)
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "runtime driver unknown", str(exc)
            )
        if identity is None:
            return CapabilityStatus(
                self.name, CapabilityState.UNKNOWN, "no target in context"
            )
        try:
            result = driver.status(self._workspace(context, identity))
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "runtime status failed", str(exc)
            )
        return CapabilityStatus(
            self.name,
            _runtime_to_capability_state(result.state),
            f"{driver.name}: {result.summary}",
        )

    # --- doctor -----------------------------------------------------------

    def _doctor_workspace(
        self, context: CapabilityContext
    ) -> RuntimeWorkspace | None:
        """Build a workspace for doctor when a target identity is available.

        Lets drivers run target-scoped diagnostics (e.g. E6-S2 R2 checking the
        configured compose file exists).  Returns ``None`` at project level (no
        target), where only driver/tool availability can be checked.
        """

        identity = context.identity
        if identity is None:
            return None
        return self._workspace(context, identity)

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        if not self.is_enabled(context):
            return ()
        try:
            driver = self._driver(context)
        except RamalioError as exc:
            return (
                CapabilityDoctorCheck(
                    check_id="RUNTIME_DRIVER",
                    status=DoctorCheckStatus.FAIL,
                    summary="runtime driver unknown",
                    details=str(exc),
                ),
            )
        checks = driver.doctor(self._doctor_workspace(context))
        return tuple(
            CapabilityDoctorCheck(
                check_id=c.check_id,
                status=DoctorCheckStatus.PASS if c.ok else DoctorCheckStatus.FAIL,
                summary=c.summary,
                details=c.details,
            )
            for c in checks
        )

    # --- lifecycle hooks --------------------------------------------------

    def handle(self, event: str, context: object) -> object:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return None
        identity = cap_ctx.identity
        if identity is None:
            return None
        driver = self._driver(cap_ctx)
        workspace = self._workspace(cap_ctx, identity)

        changed = False
        try:
            if event == _AFTER_INIT or event == _AFTER_ADOPT:
                # E10-S1 R3/R4: provision only when the matching flag is set.
                # Reading the flags via getattr keeps the capability agnostic of
                # any specific driver (the ``none`` driver has no such flags and
                # is a no-op anyway).
                flag = (
                    "provision_on_init"
                    if event == _AFTER_INIT
                    else "provision_on_adopt"
                )
                if not getattr(driver, flag, False):
                    return None
                try:
                    before = driver.status(workspace).state
                except RamalioError:
                    before = RuntimeState.UNKNOWN
                result = driver.provision(workspace)
                changed = self._resolve_changed_on_start(result, before)
            elif event == _AFTER_START:
                # E7-S0 R3/R11 (audit H3): ownership must reflect what THIS call
                # actually started.  Prefer the driver's authoritative
                # ``result.changed``; a driver knows whether it brought the
                # runtime up or merely found it running.  Only when the driver
                # does not declare it do we fall back to a state heuristic — and
                # that heuristic is fail-closed: if we could not observe the
                # runtime as clearly stopped before start(), we do NOT claim
                # ownership, so rollback never stops a preexisting runtime whose
                # prior state was UNKNOWN.
                try:
                    before = driver.status(workspace).state
                except RamalioError:
                    before = RuntimeState.UNKNOWN
                result = driver.start(workspace)
                changed = self._resolve_changed_on_start(result, before)
            elif event == _BEFORE_STOP:
                result = driver.stop(workspace)
                changed = self._resolve_changed_on_teardown(result)
            elif event == _BEFORE_DESTROY:
                result = driver.cleanup(workspace)
                changed = self._resolve_changed_on_teardown(result)
            else:
                return None
        except RamalioError as exc:
            # Preserve the partial-mutation contract (audit H4): if the driver
            # already declared whether it mutated before failing, re-raise its
            # error unchanged so the hook runner can journal the partial
            # mutation.  Otherwise the driver failed WITHOUT declaring a
            # mutation, so map to a phase-specific error with ``changed=False``
            # — a generic failure is treated as "no mutation" rather than
            # UNKNOWN, so a clean start failure is not misrecorded as an unsafe
            # rollback resource.
            from ...core.errors import PartialMutationError

            if isinstance(exc, PartialMutationError):
                raise
            if event in (_AFTER_START, _AFTER_INIT, _AFTER_ADOPT):
                raise RuntimeStartFailedError(str(exc), changed=False) from exc
            if event == _BEFORE_STOP:
                raise RuntimeStopFailedError(str(exc), changed=False) from exc
            raise RuntimeCleanupFailedError(str(exc), changed=False) from exc

        from ...hooks import HookResult, LifecycleEvent

        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary=f"runtime {event}: {result.summary}",
            compensation_available=(
                changed and event in (_AFTER_START, _AFTER_INIT, _AFTER_ADOPT)
            ),
        )

    @staticmethod
    def _resolve_changed_on_start(
        result: RuntimeResult, before: RuntimeState
    ) -> bool:
        """Whether ``start`` actually brought the runtime up (audit H3).

        Authoritative source is ``result.changed`` when the driver declares it.
        Only when it is ``None`` do we fall back to a *fail-closed* heuristic:
        we claim ownership solely when the runtime was observably STOPPED before
        the call and is now applicable.  A prior UNKNOWN/RUNNING/DEGRADED state
        yields ``False`` so a later rollback never stops a runtime this call did
        not demonstrably start.
        """

        if result.changed is not None:
            return result.changed
        if result.state is RuntimeState.NOT_APPLICABLE:
            return False
        # Fail-closed: only STOPPED -> applicable is a demonstrable start.
        return before is RuntimeState.STOPPED

    @staticmethod
    def _resolve_changed_on_teardown(result: RuntimeResult) -> bool:
        """Whether a stop/cleanup actually mutated the runtime (audit H6).

        Prefer the driver's authoritative ``result.changed``.  Only when it is
        ``None`` do we fall back to the coarse "not NOT_APPLICABLE" heuristic;
        this keeps older drivers working but a driver that returns an idempotent
        STOPPED for an already-stopped runtime should set ``changed=False`` so a
        no-op teardown is never recorded as an unsafe transaction step.
        """

        if result.changed is not None:
            return result.changed
        return result.state is not RuntimeState.NOT_APPLICABLE

    def compensate(self, event: str, context: object) -> None:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return
        identity = cap_ctx.identity
        if identity is None or event not in (
            _AFTER_START,
            _AFTER_INIT,
            _AFTER_ADOPT,
        ):
            return
        # E7-S0 R6/R7 (P4): let a compensation failure propagate.
        # LifecycleTransaction.rollback() already catches exceptions from
        # compensations and records them as rollback_errors; swallowing them
        # here would let a failed stop() be misreported as ROLLBACK_COMPLETE.
        # A runtime brought up by provision (after_init/after_adopt) is
        # compensated with the same stop() as a start (E10-S1 R8.5/AC-11): the
        # rollback never stops a preexisting runtime because ``changed`` was
        # only claimed when we demonstrably brought it up.
        driver = self._driver(cap_ctx)
        # Audit H3/F1: retire the materialize_env_file destination THIS call
        # created, if any, before/alongside stopping the runtime. The driver
        # tracks ownership per target and never touches a preexisting file.
        # A failure retiring the file must still attempt driver.stop() (never
        # abandon both compensations), then re-raise so LifecycleTransaction
        # records the failure as a rollback_error instead of losing it.
        workspace = self._workspace(cap_ctx, identity)
        compensate_env = getattr(driver, "compensate_materialize_env_file", None)
        env_error: Exception | None = None
        if callable(compensate_env):
            try:
                compensate_env(workspace)
            except Exception as exc:  # noqa: BLE001 - re-raised below, not swallowed
                env_error = exc
        driver.stop(workspace)
        if env_error is not None:
            raise env_error
