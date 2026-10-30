"""Tunnel capability wrapping an optional exposure provider (E6-S3).

Resolves a provider by name from ``[capabilities.tunnel].provider`` and
coordinates it through the E4 hooks.  The local endpoint is resolved from the
E6-S1 port reservation (R4/R5); the provider never allocates ports.  Registered
after the runtime capability so, on start, the runtime comes up before the
tunnel is opened (R13 start ordering).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from ...core.errors import (
    RamalioError,
    TunnelProviderUnknownError,
    TunnelStartFailedError,
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
from .base import (
    LocalEndpoint,
    TunnelProvider,
    TunnelResult,
    TunnelState,
    TunnelWorkspace,
)
from .zrok import PROVIDER_NAME as ZROK_PROVIDER, make_provider as make_zrok

CAPABILITY_NAME = "tunnel"

_AFTER_START = "after_start"
_BEFORE_STOP = "before_stop"
_BEFORE_DESTROY = "before_destroy"

ProviderFactory = Callable[[dict], TunnelProvider]

_PROVIDERS: dict[str, ProviderFactory] = {
    ZROK_PROVIDER: make_zrok,
}


def register_provider(name: str, factory: ProviderFactory) -> None:
    """Register a tunnel provider factory by name (R16 extension seam)."""

    _PROVIDERS[name] = factory


def _tunnel_to_capability_state(state: TunnelState) -> CapabilityState:
    return {
        TunnelState.DISABLED: CapabilityState.DISABLED,
        TunnelState.STOPPED: CapabilityState.STOPPED,
        TunnelState.STARTING: CapabilityState.ACTIVE,
        TunnelState.ACTIVE: CapabilityState.ACTIVE,
        TunnelState.DEGRADED: CapabilityState.DEGRADED,
        TunnelState.FAILED: CapabilityState.ERROR,
        TunnelState.UNKNOWN: CapabilityState.UNKNOWN,
    }[state]


class TunnelCapability(BaseCapability):
    """Coordinate an optional tunnel provider per target (E6-S3)."""

    capability_name = CAPABILITY_NAME

    def __init__(
        self,
        *,
        providers: dict[str, ProviderFactory] | None = None,
        endpoint_resolver: Callable[[CapabilityContext, str], LocalEndpoint | None]
        | None = None,
        store_base: Path | None = None,
    ) -> None:
        self._providers = providers if providers is not None else _PROVIDERS
        self._endpoint_resolver = endpoint_resolver
        self._store_base = store_base

    def is_enabled(self, context: CapabilityContext) -> bool:
        entry = context.capability_config(self.name)
        return entry is not None and entry.enabled

    def _provider_name(self, context: CapabilityContext) -> str:
        entry = context.capability_config(self.name)
        if entry is None:
            return ZROK_PROVIDER
        return str(entry.options.get("provider", ZROK_PROVIDER))

    def _provider(self, context: CapabilityContext) -> TunnelProvider:
        name = self._provider_name(context)
        factory = self._providers.get(name)
        if factory is None:
            raise TunnelProviderUnknownError(
                f"tunnel provider '{name}' is not registered"
            )
        entry = context.capability_config(self.name)
        options = dict(entry.options) if entry is not None else {}
        return factory(options)

    def validate_config(self, context: CapabilityContext) -> None:
        self._provider(context)

    def _workspace(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> TunnelWorkspace:
        root = context.config.repository_root
        worktree = (root / Path(*identity.worktree_path.parts)).resolve()
        return TunnelWorkspace(
            target=identity.target.value,
            worktree_path=worktree,
            identity=identity,
            repository_root=root,
        )

    def _endpoint(
        self, context: CapabilityContext, target: str
    ) -> LocalEndpoint | None:
        """Resolve the local endpoint from the reserved port (R4/R5)."""

        if self._endpoint_resolver is not None:
            return self._endpoint_resolver(context, target)
        if not context.config.ports.enabled:
            return None
        from ...resources.ports import PortReservationStore

        store = PortReservationStore(
            context.config.repository_root, base=self._store_base
        )
        reservation = store.load(target)
        if reservation is None:
            return None
        return LocalEndpoint(host="127.0.0.1", port=reservation.port)

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "tunnel disabled"
            )
        identity = context.identity
        if identity is None:
            return CapabilityStatus(
                self.name, CapabilityState.UNKNOWN, "no target in context"
            )
        try:
            provider = self._provider(context)
            result = provider.status(self._workspace(context, identity))
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "tunnel status failed", str(exc)
            )
        summary = result.summary
        if result.public_url:
            summary = f"{summary} ({result.public_url})"
        return CapabilityStatus(
            self.name, _tunnel_to_capability_state(result.state), summary
        )

    # --- doctor -----------------------------------------------------------

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        if not self.is_enabled(context):
            return ()
        try:
            provider = self._provider(context)
        except RamalioError as exc:
            return (
                CapabilityDoctorCheck(
                    check_id="TUNNEL_PROVIDER",
                    status=DoctorCheckStatus.FAIL,
                    summary="tunnel provider unknown",
                    details=str(exc),
                ),
            )
        checks = provider.doctor(None)
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
        provider = self._provider(cap_ctx)
        workspace = self._workspace(cap_ctx, identity)

        changed = False
        if event == _AFTER_START:
            endpoint = self._endpoint(cap_ctx, identity.target.value)
            if endpoint is None:
                raise TunnelStartFailedError(
                    f"tunnel for '{identity.target.value}' has no local endpoint; "
                    "enable [ports] or provide an endpoint resolver"
                )
            # E7-S0 R3/R11 (audit H4): ownership must reflect what THIS call
            # actually started.  Prefer the provider's authoritative
            # ``result.changed``; the provider knows whether it opened a new
            # exposure or found one already active.  Only when it is undeclared
            # do we fall back to a *fail-closed* heuristic: we claim ownership
            # solely when the tunnel was observably not active before the call
            # (STOPPED/DISABLED, never UNKNOWN) and is now ACTIVE, so rollback
            # never stops a tunnel whose prior state was indeterminate.
            try:
                before = provider.status(workspace).state
            except RamalioError:
                before = TunnelState.UNKNOWN
            result = provider.start(workspace, endpoint)
            changed = self._resolve_changed_on_start(result, before)
        elif event in (_BEFORE_STOP, _BEFORE_DESTROY):
            # Only report a mutation if a tunnel actually existed to tear down.
            try:
                before = provider.status(workspace).state
            except RamalioError:
                before = TunnelState.UNKNOWN
            result = provider.cleanup(workspace) if event == _BEFORE_DESTROY else provider.stop(workspace)
            changed = self._resolve_changed_on_teardown(result, before)
        else:
            return None

        from ...hooks import HookResult, LifecycleEvent

        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary=f"tunnel {event}: {result.summary}",
            compensation_available=changed and event == _AFTER_START,
        )

    @staticmethod
    def _resolve_changed_on_start(
        result: "TunnelResult", before: TunnelState
    ) -> bool:
        """Whether ``start`` actually opened a new exposure (audit H4).

        Authoritative source is ``result.changed`` when the provider declares
        it.  Only when it is ``None`` do we fall back to a *fail-closed*
        heuristic: claim ownership solely when the tunnel was observably not
        active before the call (STOPPED/DISABLED, never UNKNOWN) and is now
        ACTIVE.  A prior UNKNOWN state yields ``False`` so rollback never stops a
        tunnel that may have preexisted.
        """

        if result.changed is not None:
            return result.changed
        if result.state is not TunnelState.ACTIVE:
            return False
        return before in (TunnelState.STOPPED, TunnelState.DISABLED)

    @staticmethod
    def _resolve_changed_on_teardown(
        result: "TunnelResult", before: TunnelState
    ) -> bool:
        """Whether a stop/cleanup actually tore an exposure down (audit H4/H6).

        Prefer the provider's authoritative ``result.changed``.  Only when it is
        ``None`` do we fall back to "a tunnel existed before" (not
        STOPPED/DISABLED), so a teardown over an already-absent tunnel is not
        recorded as a mutation.
        """

        if result.changed is not None:
            return result.changed
        return before not in (TunnelState.STOPPED, TunnelState.DISABLED)

    def compensate(self, event: str, context: object) -> None:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return
        identity = cap_ctx.identity
        if identity is None or event != _AFTER_START:
            return
        # E7-S0 R6/R7 (P4): let a compensation failure propagate so
        # LifecycleTransaction.rollback() can record it as a rollback_error
        # instead of silently reporting ROLLBACK_COMPLETE.
        self._provider(cap_ctx).stop(self._workspace(cap_ctx, identity))
