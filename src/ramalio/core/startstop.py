"""Start/stop lifecycle services: suspend and resume a workspace (E3-S2).

In a Git-only project without active capabilities there are no operational
resources to suspend or resume, so ``start``/``stop`` are valid, idempotent
no-ops that keep the Git workspace intact (spec 5, INV-01/INV-04).  No artificial
``stopped=true`` state is ever persisted (R8/INV-03): operational state will be
derived from real capability state once E4 introduces it.

The services consume :class:`~ramalio.core.status.WorkspaceStatus`
(E3-S1) instead of re-deriving Git facts (8.1), and expose an internal handler
seam so E4 can plug capability start/stop actions in without changing the public
CLI surface (INV-05, R11, 8.4).

Neither service mutates Git or the filesystem, nor performs process/port
discovery (R14/R15).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..config.loader import resolve_project_config
from ..config.models import ResolvedProjectConfig
from ..git.repository import GitRepository
from .errors import (
    WorkspaceInconsistentError,
    WorkspaceNotActiveError,
    WorkspaceNotFoundError,
)
from .naming import ResolvedWorkspaceIdentity
from .status import GetWorkspaceStatusService, WorkspaceState, WorkspaceStatus
from .worktree import WorkspaceObserver

# States that are operationally addressable by start/stop (R2).
_ADDRESSABLE = frozenset({WorkspaceState.READY, WorkspaceState.DIRTY})


@dataclass(frozen=True, slots=True)
class StartOutcome:
    """Structured result of ``start`` (R13)."""

    target: str
    workspace_path: Path
    resources_started: int
    no_op: bool

    def render_lines(self) -> str:
        return "\n".join(
            (
                f"target: {self.target}",
                f"workspace: {self.workspace_path}",
                f"resources_started: {self.resources_started}",
                f"no_op: {'true' if self.no_op else 'false'}",
            )
        )


@dataclass(frozen=True, slots=True)
class StopOutcome:
    """Structured result of ``stop`` (R13)."""

    target: str
    workspace_path: Path
    resources_stopped: int
    no_op: bool

    def render_lines(self) -> str:
        return "\n".join(
            (
                f"target: {self.target}",
                f"workspace: {self.workspace_path}",
                f"resources_stopped: {self.resources_stopped}",
                f"no_op: {'true' if self.no_op else 'false'}",
            )
        )


class _WorkspaceOperationBase:
    """Shared identity resolution + precondition matrix for start/stop (T4).

    Subclasses only differ in the operational verb; the precondition checks and
    the E3 Git-only no-op semantics are shared to avoid duplicating rules (7.2).
    """

    def __init__(
        self,
        config: ResolvedProjectConfig,
        *,
        repository: GitRepository | None = None,
        observer: WorkspaceObserver | None = None,
        status_service: GetWorkspaceStatusService | None = None,
        registry=None,
        lock_manager=None,
    ) -> None:
        self._config = config
        self._repo = (
            repository
            if repository is not None
            else GitRepository.from_root(config.repository_root)
        )
        self._observer = (
            observer if observer is not None else WorkspaceObserver(self._repo)
        )
        if registry is None:
            from ..capabilities import default_registry

            registry = default_registry()
        self._registry = registry
        self._lock_manager = lock_manager
        self._status_service = (
            status_service
            if status_service is not None
            else GetWorkspaceStatusService(
                config,
                repository=self._repo,
                observer=self._observer,
                registry=self._registry,
            )
        )

    def _lifecycle_lock(self, target: str, *, operation: str):
        """Return the per-target lifecycle lock context for a mutable op (E7-S1).

        ``start``/``stop`` are mutable operations on the target's operational
        resources, so they serialize with init/adopt/destroy on the same target
        (R3) while leaving distinct targets free to proceed in parallel (R4).
        """

        from .locking import target_lifecycle_lock

        return target_lifecycle_lock(
            self._config.repository_root,
            target,
            operation=operation,
            lock_manager=self._lock_manager,
        )

    def _resolve_status(self, raw_target: str) -> WorkspaceStatus:
        """Resolve the target's status via E3-S1 (R1)."""

        return self._status_service.run(raw_target)

    def _resolve_identity(self, raw_target: str) -> ResolvedWorkspaceIdentity:
        """Resolve the full workspace identity for hook context (E4-S1/E4-S2)."""

        from ..config.target import build_target_normalizer, build_workspace_naming

        normalizer = build_target_normalizer(self._config)
        result = normalizer.normalize(raw_target)
        naming = build_workspace_naming(self._config)
        return naming.resolve(result.target)

    def _require_addressable(self, status: WorkspaceStatus) -> None:
        """Enforce the precondition matrix (R2-R5, T4).

        READY/DIRTY are addressable (dirty does not block).  MISSING,
        BRANCH_ONLY and anomalous states fail closed with the appropriate stable
        error and, for BRANCH_ONLY, the ``adopt`` guidance surfaced by status.
        """

        state = status.state
        if state in _ADDRESSABLE:
            return

        target = status.identity.target
        if state is WorkspaceState.MISSING:
            raise WorkspaceNotFoundError(
                f"no managed workspace found for target '{target}'."
            )
        if state is WorkspaceState.BRANCH_ONLY:
            raise WorkspaceNotActiveError(
                f"target '{target}' has a branch but no active worktree; "
                "there is nothing to start/stop. Use `adopt` to activate it."
            )
        # INCONSISTENT / DETACHED / PRUNABLE (R5).
        reason = status.reason or state.value
        raise WorkspaceInconsistentError(
            f"target '{target}' is in an anomalous state ({state.value}: "
            f"{reason}); start/stop is blocked. Inspect with `status`."
        )

    def _operational_handlers(self) -> Sequence[object]:
        """Return configured operational handlers (extension seam, R11, 8.4).

        In E3 there is no capability framework, so there are never any handlers.
        E4 will populate this without changing the public command surface
        (INV-05).  Kept as a method so the no-op count is derived from a real
        (empty) collection rather than a hardcoded zero.
        """

        return ()

    def _run_lifecycle(
        self,
        status: WorkspaceStatus,
        *,
        operation: str,
        before,
        after,
        identity: ResolvedWorkspaceIdentity,
    ) -> int:
        """Run before_* / after_* capability hooks around a Git-only no-op (E4-S1).

        Returns the number of capability resources acted upon (0 in a Git-only
        project without capabilities).  before failures block; after failures
        compensate via the common :class:`LifecycleTransaction` then raise
        (E7-S0 R11/R12, INV-03/INV-04).  With an empty registry this is a pure
        no-op and the E3-S2 semantics are preserved.
        """

        from ..capabilities import verify_capability_configuration
        from ..capabilities.base import CapabilityContext
        from ..hooks import HookContext, HookJournal, HookRunner
        from ..transactions import LifecycleTransaction, raise_if_unsafe

        # E4-S0 R13 fail-closed: reject unknown/invalid capability configuration
        # before running any hook, uniformly with init/adopt/destroy.
        verify_capability_configuration(self._registry, self._config, identity)

        runner = HookRunner(self._registry)
        hook_ctx = HookContext(
            capability_context=CapabilityContext(
                config=self._config, identity=identity
            ),
            operation=operation,
        )
        journal = HookJournal()
        transaction = LifecycleTransaction(operation)
        # E7-S0 R2/R11/R12: the WHOLE mutable lifecycle runs inside the
        # transaction.  ``before_stop`` is not merely a guard — it actively
        # tears resources down (tunnel/runtime/processes/tmux), so a failure
        # there must also trigger rollback of what was already done.  Wrapping
        # both events guarantees no mutation escapes the common mechanism.
        try:
            before_results = runner.run_event(
                before, hook_ctx, journal=journal, transaction=transaction
            )
            # Git-only core operation is a no-op; nothing to mutate.
            after_results = runner.run_event(
                after, hook_ctx, journal=journal, transaction=transaction
            )
        except BaseException as exc:  # includes KeyboardInterrupt (R14)
            outcome = transaction.rollback(exc)
            # E7-S0 R6/R7/R16: surface a partial/unsafe rollback instead of
            # discarding the TransactionOutcome; a resource left in an unknown
            # state must be diagnosable, never silently swallowed.
            raise_if_unsafe(outcome, operation=operation)
            raise
        # P10 / audit H5: count resources ACTUALLY changed across BOTH phases.
        # ``stop`` mutates in ``before_stop`` (built-in capabilities tear
        # resources down there and implement no ``after_stop``), while ``start``
        # mutates in ``after_start``; counting only the ``after`` phase would
        # always report ``resources_stopped=0`` for stop.  A capability that
        # reports success with ``changed=False`` (e.g. a reused port reservation,
        # an already-running runtime) is a no-op and must not inflate the count
        # or flip ``no_op`` to False.
        return sum(
            1 for result in (*before_results, *after_results) if result.changed
        )


class StartWorkspaceService(_WorkspaceOperationBase):
    """Orchestrate ``ramalio start <target>`` (8.1, T2)."""

    @classmethod
    def from_directory(
        cls, start: Path | str | None = None
    ) -> "StartWorkspaceService":
        return cls(resolve_project_config(start))

    def run(self, raw_target: str) -> StartOutcome:
        status = self._resolve_status(raw_target)
        self._require_addressable(status)

        from ..hooks import LifecycleEvent

        identity = self._resolve_identity(raw_target)
        with self._lifecycle_lock(status.identity.target, operation="start"):
            resources = self._run_lifecycle(
                status,
                operation="start",
                before=LifecycleEvent.BEFORE_START,
                after=LifecycleEvent.AFTER_START,
                identity=identity,
            )
        return StartOutcome(
            target=status.identity.target,
            workspace_path=status.identity.expected_worktree_path,
            resources_started=resources,
            no_op=resources == 0,
        )


class StopWorkspaceService(_WorkspaceOperationBase):
    """Orchestrate ``ramalio stop <target>`` (8.1, T3)."""

    @classmethod
    def from_directory(
        cls, start: Path | str | None = None
    ) -> "StopWorkspaceService":
        return cls(resolve_project_config(start))

    def run(self, raw_target: str) -> StopOutcome:
        status = self._resolve_status(raw_target)
        self._require_addressable(status)

        from ..hooks import LifecycleEvent

        identity = self._resolve_identity(raw_target)
        with self._lifecycle_lock(status.identity.target, operation="stop"):
            resources = self._run_lifecycle(
                status,
                operation="stop",
                before=LifecycleEvent.BEFORE_STOP,
                after=LifecycleEvent.AFTER_STOP,
                identity=identity,
            )
        return StopOutcome(
            target=status.identity.target,
            workspace_path=status.identity.expected_worktree_path,
            resources_stopped=resources,
            no_op=resources == 0,
        )
