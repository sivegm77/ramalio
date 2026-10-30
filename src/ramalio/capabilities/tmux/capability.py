"""Optional tmux capability (E5-S0).

Associates a deterministic, target-owned tmux session with a workspace, without
making tmux a core dependency (INV: core works without tmux).  Ownership is
verified via a session environment marker so a preexisting, unrelated session
that happens to share the derived name is never reused or killed (R10).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ...core.errors import (
    RamalioError,
    TmuxSessionOwnershipError,
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
from .runtime import (
    OWNER_ENV_KEY,
    SessionPolicy,
    TmuxConfig,
    TmuxRunner,
    derive_session_name,
    parse_tmux_config,
)

CAPABILITY_NAME = "tmux"

_AFTER_INIT = "after_init"
_AFTER_START = "after_start"
_BEFORE_STOP = "before_stop"
_BEFORE_DESTROY = "before_destroy"


class TmuxCapability(BaseCapability):
    """Manage a per-target tmux session (E5-S0)."""

    capability_name = CAPABILITY_NAME

    def __init__(self, *, runner: TmuxRunner | None = None) -> None:
        self._runner = runner or TmuxRunner()

    # --- config -----------------------------------------------------------

    def _config(self, context: CapabilityContext) -> TmuxConfig:
        entry = context.capability_config(self.name)
        options = entry.options if entry is not None else {}
        return parse_tmux_config(options)

    def validate_config(self, context: CapabilityContext) -> None:
        self._config(context)

    def _session_name(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> str:
        cfg = self._config(context)
        return derive_session_name(cfg.session_pattern, identity.target.value)

    def _worktree_path(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> str:
        root = context.config.repository_root
        return str((root / Path(*identity.worktree_path.parts)).resolve())

    # --- ownership --------------------------------------------------------

    def _owned(self, name: str, target: str) -> bool:
        """Whether an existing session is owned by ``target`` via marker (R10)."""

        marker = self._runner.get_session_env(name, OWNER_ENV_KEY)
        return marker == target

    def _ensure_session(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> bool:
        """Create the session if missing; return True if created (R4/R12).

        If a session with the derived name exists but is not owned by this
        target, refuse (R10).
        """

        name = self._session_name(context, identity)
        target = identity.target.value
        if self._runner.has_session(name):
            if not self._owned(name, target):
                raise TmuxSessionOwnershipError(
                    f"tmux session '{name}' exists but is not owned by target "
                    f"'{target}'; refusing to reuse or modify it"
                )
            return False  # idempotent: already present and owned
        self._runner.new_session(name, cwd=self._worktree_path(context, identity))
        self._runner.set_session_env(name, OWNER_ENV_KEY, target)
        return True

    def _kill_if_owned(
        self, context: CapabilityContext, identity: ResolvedWorkspaceIdentity
    ) -> bool:
        """Kill the session only if owned by this target (R9/R10)."""

        name = self._session_name(context, identity)
        target = identity.target.value
        if not self._runner.has_session(name):
            return False
        if not self._owned(name, target):
            raise TmuxSessionOwnershipError(
                f"tmux session '{name}' is not owned by target '{target}'; "
                "refusing to kill it"
            )
        self._runner.kill_session(name)
        return True

    # --- status -----------------------------------------------------------

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "capability disabled"
            )
        if not self._runner.available:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "tmux not available"
            )
        identity = context.identity
        if identity is None:
            return CapabilityStatus(
                self.name, CapabilityState.UNKNOWN, "no target in context"
            )
        try:
            name = self._session_name(context, identity)
        except RamalioError as exc:
            return CapabilityStatus(
                self.name, CapabilityState.ERROR, "invalid session name", str(exc)
            )
        if self._runner.has_session(name):
            state = (
                CapabilityState.ACTIVE
                if self._owned(name, identity.target.value)
                else CapabilityState.DEGRADED
            )
            summary = (
                f"session '{name}' running"
                if state is CapabilityState.ACTIVE
                else f"session '{name}' exists but not owned"
            )
            return CapabilityStatus(self.name, state, summary)
        return CapabilityStatus(
            self.name, CapabilityState.STOPPED, f"session '{name}' missing"
        )

    # --- doctor -----------------------------------------------------------

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        if not self.is_enabled(context):
            return ()
        available = self._runner.available
        return (
            CapabilityDoctorCheck(
                check_id="TMUX_AVAILABLE",
                status=DoctorCheckStatus.PASS if available else DoctorCheckStatus.FAIL,
                summary="tmux available" if available else "tmux not found on PATH",
                remediation=None if available else "Install tmux to use this capability.",
            ),
        )

    # --- lifecycle hooks --------------------------------------------------

    def handle(self, event: str, context: object) -> object:
        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return None
        identity = cap_ctx.identity
        if identity is None:
            return None
        cfg = self._config(cap_ctx)

        changed = False
        if event == _AFTER_INIT and cfg.create_on_init:
            changed = self._ensure_session(cap_ctx, identity)
        elif event == _AFTER_START:
            # Ensure the required session exists on start (R5).
            changed = self._ensure_session(cap_ctx, identity)
        elif event == _BEFORE_STOP:
            if cfg.stop_policy is SessionPolicy.KILL:
                changed = self._kill_if_owned(cap_ctx, identity)
        elif event == _BEFORE_DESTROY:
            if cfg.destroy_policy is SessionPolicy.KILL:
                changed = self._kill_if_owned(cap_ctx, identity)
        else:
            return None

        from ...hooks import HookResult, LifecycleEvent

        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary=f"tmux {event}",
            compensation_available=changed and event in (_AFTER_INIT, _AFTER_START),
        )

    def compensate(self, event: str, context: object) -> None:
        """Kill a session created during ``event`` (E4-S1 R6)."""

        cap_ctx = getattr(context, "capability_context", None)
        if cap_ctx is None or not self.is_enabled(cap_ctx):
            return
        identity = cap_ctx.identity
        if identity is None:
            return
        if event in (_AFTER_INIT, _AFTER_START):
            # E7-S0 R6/R7 (P4): let a failure propagate to
            # LifecycleTransaction.rollback(), which records it as a
            # rollback_error instead of silently reporting ROLLBACK_COMPLETE.
            self._kill_if_owned(cap_ctx, identity)
