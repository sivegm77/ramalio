"""Bootstrap capability: dependency provisioning + readiness (E10-S2).

Models "the workspace is ready only after dependencies + readiness" as an
optional capability with an explicit provider (``composer``), never as Laravel
support nor arbitrary project script hooks (spec §2).  It participates in
``after_init``/``after_adopt`` (per flags) and reuses the existing registry,
HookRunner, LifecycleTransaction, locks, SafeProcessRunner and — for the runtime
executor — the E10-S1 ``RuntimeCommandExecutor`` protocol (never Docker Compose
directly).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from ...core.errors import (
    CapabilityConfigInvalidError,
    RamalioError,
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
from .composer import COMPOSER_EXECUTABLE, ComposerProvider
from .models import (
    EXECUTOR_RUNTIME,
    PROVIDER_COMPOSER,
    BootstrapConfig,
    parse_bootstrap_config,
)

CAPABILITY_NAME = "bootstrap"

_AFTER_INIT = "after_init"
_AFTER_ADOPT = "after_adopt"

# Explicit provider registry (R1): no dynamic plugin discovery.  E10-S2
# registers only ``composer``.
_PROVIDERS: dict[str, Callable[..., ComposerProvider]] = {
    PROVIDER_COMPOSER: ComposerProvider,
}


class BootstrapCapability(BaseCapability):
    """Dependency provisioning + readiness capability (E10-S2)."""

    capability_name = CAPABILITY_NAME

    # --- config -----------------------------------------------------------

    def _config(self, context: CapabilityContext) -> BootstrapConfig:
        entry = context.capability_config(self.name)
        options = dict(entry.options) if entry is not None else {}
        # ``enabled`` lives in options for the generic parser; include it so the
        # bootstrap parser sees the full section.
        if entry is not None:
            options.setdefault("enabled", entry.enabled)
        return parse_bootstrap_config(options)

    def is_enabled(self, context: CapabilityContext) -> bool:
        entry = context.capability_config(self.name)
        return entry is not None and entry.enabled

    def validate_config(self, context: CapabilityContext) -> None:
        config = self._config(context)
        if not config.enabled:
            return
        if config.provider not in _PROVIDERS:
            raise CapabilityConfigInvalidError(
                f"bootstrap: unknown provider '{config.provider}'"
            )
        # R4: executor='runtime' requires a runtime that implements command
        # execution; validate before any mutation (fail config/doctor).
        if config.executor == EXECUTOR_RUNTIME:
            self._require_runtime_executor(context)

    def _require_runtime_executor(self, context: CapabilityContext):
        from ..runtime import RuntimeCapability

        runtime = RuntimeCapability()
        if context.capability_config("runtime") is None:
            raise CapabilityConfigInvalidError(
                "bootstrap: executor='runtime' requires a configured "
                "[capabilities.runtime] with a driver that supports command "
                "execution"
            )
        executor = runtime.resolve_command_executor(context)
        if executor is None:
            raise CapabilityConfigInvalidError(
                "bootstrap: executor='runtime' requires a runtime driver that "
                "implements command execution (e.g. docker-compose); the "
                "configured driver does not support it"
            )
        return executor

    # --- helpers ----------------------------------------------------------

    def _worktree_path(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> Path:
        root = context.config.repository_root
        return (root / Path(*identity.worktree_path.parts)).resolve()

    def _provider(
        self, context: CapabilityContext, config: BootstrapConfig, worktree: Path
    ) -> ComposerProvider:
        factory = _PROVIDERS[config.provider]
        return factory(config, worktree_path=worktree)

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

        worktree = self._worktree_path(cap_ctx, identity)
        provider = self._provider(cap_ctx, config, worktree)

        executor = scope = workspace = None
        if config.executor == EXECUTOR_RUNTIME:
            executor = self._require_runtime_executor(cap_ctx)
            from ..runtime import RuntimeCapability
            from ..runtime.base import RuntimeScope

            runtime = RuntimeCapability()
            scope = RuntimeScope.WORKSPACE
            workspace = runtime.workspace_for(cap_ctx, identity)

        # Composer install is the idempotent operation (R8); readiness is
        # validated inside provision().  A failure propagates and the E10-S0
        # transaction contract handles diagnosis/rollback (§6): the capability
        # cannot prove file-by-file ownership, so it declares no compensation.
        provider.provision(executor=executor, scope=scope, workspace=workspace)

        from ...hooks import HookResult, LifecycleEvent

        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=True,
            summary=f"bootstrap {config.provider} ({config.executor})",
            # The provider cannot demonstrate file-by-file ownership, so it does
            # not offer a compensation; the transaction records the mutation as
            # NOT_SAFE and keeps it diagnosable (§6).
            compensation_available=False,
        )

    # No compensate(): bootstrap never deletes preexisting dependencies (§6, R9).

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        entry = context.capability_config(self.name)
        if entry is None or not entry.enabled:
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "bootstrap not configured"
            )
        try:
            config = self._config(context)
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "bootstrap config invalid", str(exc)
            )
        identity = context.identity
        if identity is None:
            # Config valid but no target: READY (R10).
            return CapabilityStatus(
                self.name, CapabilityState.READY, "bootstrap configured"
            )
        worktree = self._worktree_path(context, identity)
        provider = self._provider(context, config, worktree)
        if provider.readiness_ok():
            return CapabilityStatus(
                self.name, CapabilityState.READY, "artifacts present"
            )
        return CapabilityStatus(
            self.name, CapabilityState.DEGRADED, "required artifacts missing"
        )

    # --- doctor -----------------------------------------------------------

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        entry = context.capability_config(self.name)
        if entry is None or not entry.enabled:
            return ()
        checks: list[CapabilityDoctorCheck] = []
        try:
            config = self._config(context)
        except RamalioError as exc:
            return (
                CapabilityDoctorCheck(
                    check_id="BOOTSTRAP_CONFIG",
                    status=DoctorCheckStatus.FAIL,
                    summary="bootstrap configuration is invalid",
                    details=str(exc),
                ),
            )

        # Provider validity.
        checks.append(
            CapabilityDoctorCheck(
                check_id="BOOTSTRAP_PROVIDER",
                status=(
                    DoctorCheckStatus.PASS
                    if config.provider in _PROVIDERS
                    else DoctorCheckStatus.FAIL
                ),
                summary=f"provider '{config.provider}'",
            )
        )

        # Executor + runtime support (R4/R10) — validated without installing.
        if config.executor == EXECUTOR_RUNTIME:
            try:
                self._require_runtime_executor(context)
                checks.append(
                    CapabilityDoctorCheck(
                        check_id="BOOTSTRAP_RUNTIME_EXEC",
                        status=DoctorCheckStatus.PASS,
                        summary="runtime supports command execution",
                    )
                )
            except RamalioError as exc:
                checks.append(
                    CapabilityDoctorCheck(
                        check_id="BOOTSTRAP_RUNTIME_EXEC",
                        status=DoctorCheckStatus.FAIL,
                        summary="runtime executor not supported",
                        details=str(exc),
                    )
                )
        else:
            import shutil

            available = shutil.which(COMPOSER_EXECUTABLE) is not None
            checks.append(
                CapabilityDoctorCheck(
                    check_id="BOOTSTRAP_COMPOSER",
                    status=(
                        DoctorCheckStatus.PASS
                        if available
                        else DoctorCheckStatus.WARN
                    ),
                    summary=(
                        f"'{COMPOSER_EXECUTABLE}' available"
                        if available
                        else f"'{COMPOSER_EXECUTABLE}' not found on PATH"
                    ),
                    remediation=None
                    if available
                    else f"Install '{COMPOSER_EXECUTABLE}' and ensure it is on PATH.",
                )
            )
        return tuple(checks)
