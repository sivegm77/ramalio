"""Data capability: isolated PostgreSQL data provisioning (E10-S3).

Copies the base PostgreSQL database into an isolated per-target database over
the E10-S1 :class:`RuntimeCommandExecutor` (never Docker Compose directly).
Registered after runtime and before bootstrap.  Provider registry is explicit
with a single ``postgres`` provider.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ...core.errors import (
    CapabilityConfigInvalidError,
    RamalioError,
    ProjectConfigInvalidError,
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
from .models import (
    CLEANUP_RUNTIME,
    PROVIDER_POSTGRES,
    DataConfig,
    parse_data_config,
)
from .postgres import PostgresProvider

CAPABILITY_NAME = "data"

_AFTER_INIT = "after_init"
_AFTER_ADOPT = "after_adopt"

# Explicit provider registry (R1): only postgres in E10-S3.
_PROVIDERS: dict[str, Callable[..., PostgresProvider]] = {
    PROVIDER_POSTGRES: PostgresProvider,
}


class DataCapability(BaseCapability):
    """Isolated PostgreSQL data provisioning (E10-S3)."""

    capability_name = CAPABILITY_NAME

    # --- config -----------------------------------------------------------

    def _config(self, context: CapabilityContext) -> DataConfig:
        entry = context.capability_config(self.name)
        options = dict(entry.options) if entry is not None else {}
        if entry is not None:
            options.setdefault("enabled", entry.enabled)
        return parse_data_config(options)

    def is_enabled(self, context: CapabilityContext) -> bool:
        entry = context.capability_config(self.name)
        return entry is not None and entry.enabled

    def validate_config(self, context: CapabilityContext) -> None:
        config = self._config(context)
        if not config.enabled:
            return
        if config.provider not in _PROVIDERS:
            raise CapabilityConfigInvalidError(
                f"data: unknown provider '{config.provider}'"
            )
        # R2: the provider requires a runtime that implements command execution.
        self._require_runtime_executor(context)
        # cleanup_mode='runtime' requires a Docker Compose runtime with
        # remove_volumes_on_destroy=true, else PROJECT_CONFIG_INVALID (R11/§3).
        if config.cleanup_mode == CLEANUP_RUNTIME:
            self._require_runtime_volume_cleanup(context)

    def _require_runtime_executor(self, context: CapabilityContext):
        from ..runtime import RuntimeCapability

        if context.capability_config("runtime") is None:
            raise CapabilityConfigInvalidError(
                "data: requires a configured [capabilities.runtime] with a "
                "driver that supports command execution"
            )
        runtime = RuntimeCapability()
        executor = runtime.resolve_command_executor(context)
        if executor is None:
            raise CapabilityConfigInvalidError(
                "data: requires a runtime driver that implements command "
                "execution (e.g. docker-compose); the configured driver does "
                "not support it"
            )
        return executor

    def _require_runtime_volume_cleanup(self, context: CapabilityContext) -> None:
        """Enforce cleanup_mode='runtime' preconditions (R11).

        The runtime must be a driver that removes target volumes on destroy
        (``remove_volumes_on_destroy=true``); otherwise the delegated cleanup
        contract cannot be honored and the configuration is rejected with
        PROJECT_CONFIG_INVALID.  There is NO automatic ``drop database``.
        """

        from ..runtime import RuntimeCapability

        runtime = RuntimeCapability()
        try:
            driver = runtime._driver(  # noqa: SLF001 - internal resolution
                context
            )
        except RamalioError as exc:
            raise ProjectConfigInvalidError(
                f"data: cleanup_mode='runtime' requires a valid runtime: {exc}"
            ) from exc
        if not getattr(driver, "remove_volumes_on_destroy", False):
            raise ProjectConfigInvalidError(
                "data: cleanup_mode='runtime' requires the runtime to set "
                "remove_volumes_on_destroy=true so target volumes are actually "
                "removed on destroy; there is no automatic drop database"
            )

    # --- helpers ----------------------------------------------------------

    def _provider(
        self, context: CapabilityContext, config: DataConfig, identity
    ) -> PostgresProvider:
        from ..runtime import RuntimeCapability

        runtime = RuntimeCapability()
        executor = self._require_runtime_executor(context)
        target_workspace = runtime.workspace_for(context, identity)
        factory = _PROVIDERS[config.provider]
        return factory(
            config,
            executor=executor,
            source_workspace=None,  # project scope
            target_workspace=target_workspace,
        )

    # --- lifecycle hooks --------------------------------------------------

    def handle(self, event: str, context: object) -> object:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return None
        identity = cap_ctx.identity
        if identity is None:
            return None

        config = self._config(cap_ctx)
        if not config.enabled:
            return None
        if event == _AFTER_INIT and not config.on_init:
            return None
        if event == _AFTER_ADOPT and not config.on_adopt:
            return None
        if event not in (_AFTER_INIT, _AFTER_ADOPT):
            return None

        provider = self._provider(cap_ctx, config, identity)
        changed = provider.provision()

        from ...hooks import HookResult, LifecycleEvent

        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary=f"data {config.provider} restored into target",
            # The provider never owns the runtime/volumes; those are compensated
            # by the runtime capability under the transaction.  A partial
            # restore is surfaced via the provider's PartialMutationError, so no
            # compensation is offered here (R12).
            compensation_available=False,
        )

    # No compensate(): the provider never touches source; the target runtime/
    # volumes are owned and compensated by the runtime capability (R12).

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        entry = context.capability_config(self.name)
        if entry is None or not entry.enabled:
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "data not configured"
            )
        try:
            config = self._config(context)
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "data config invalid", str(exc)
            )
        identity = context.identity
        if identity is None:
            return CapabilityStatus(
                self.name, CapabilityState.READY, "data configured"
            )
        try:
            provider = self._provider(context, config, identity)
            ready = provider.target_ready()
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.DEGRADED, "target not ready", str(exc)
            )
        if ready:
            return CapabilityStatus(
                self.name, CapabilityState.ACTIVE, "target database responds"
            )
        return CapabilityStatus(
            self.name, CapabilityState.DEGRADED, "target database not responding"
        )

    # --- doctor -----------------------------------------------------------

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        entry = context.capability_config(self.name)
        if entry is None or not entry.enabled:
            return ()
        try:
            config = self._config(context)
        except RamalioError as exc:
            return (
                CapabilityDoctorCheck(
                    check_id="DATA_CONFIG",
                    status=DoctorCheckStatus.FAIL,
                    summary="data configuration is invalid",
                    details=str(exc),
                ),
            )

        checks: list[CapabilityDoctorCheck] = [
            CapabilityDoctorCheck(
                check_id="DATA_PROVIDER",
                status=(
                    DoctorCheckStatus.PASS
                    if config.provider in _PROVIDERS
                    else DoctorCheckStatus.FAIL
                ),
                summary=f"provider '{config.provider}'",
            )
        ]

        # Runtime exec support (R2/R13) — validated without dump/restore.
        try:
            self._require_runtime_executor(context)
            checks.append(
                CapabilityDoctorCheck(
                    check_id="DATA_RUNTIME_EXEC",
                    status=DoctorCheckStatus.PASS,
                    summary="runtime supports command execution",
                )
            )
        except RamalioError as exc:
            checks.append(
                CapabilityDoctorCheck(
                    check_id="DATA_RUNTIME_EXEC",
                    status=DoctorCheckStatus.FAIL,
                    summary="runtime executor not supported",
                    details=str(exc),
                )
            )

        # cleanup_mode='runtime' precondition (R11/R10).
        if config.cleanup_mode == CLEANUP_RUNTIME:
            try:
                self._require_runtime_volume_cleanup(context)
                checks.append(
                    CapabilityDoctorCheck(
                        check_id="DATA_CLEANUP_RUNTIME",
                        status=DoctorCheckStatus.PASS,
                        summary="runtime removes target volumes on destroy",
                    )
                )
            except RamalioError as exc:
                checks.append(
                    CapabilityDoctorCheck(
                        check_id="DATA_CLEANUP_RUNTIME",
                        status=DoctorCheckStatus.FAIL,
                        summary="cleanup_mode='runtime' precondition unmet",
                        details=str(exc),
                    )
                )
        return tuple(checks)
