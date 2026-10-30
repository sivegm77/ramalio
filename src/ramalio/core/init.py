"""Init lifecycle service: create a managed workspace (E2-S1).

``InitWorkspaceService`` orchestrates the first usable lifecycle operation
(7.1): it turns ``target + project configuration`` into ``branch + Git
worktree`` without depending on tmux, Docker, Kiro, processes, ports or
capabilities (INV-06/E2-S1).

Flow (7.1)::

    resolve project
          -> normalize + validate target
          -> derive identity
          -> observe current Git state
          -> preflight
          -> create branch + worktree
          -> verify postconditions
          -> return success

Safety design:

* The branch and the worktree are each registered as their own, separately
  compensable :class:`~ramalio.transactions.LifecycleTransaction` step
  the moment they are created (E7-S0 R2): there is a single rollback mechanism
  for every mutable lifecycle operation, not a Git-specific ``MutationJournal``
  layered underneath it.
* Preconditions fail closed and mutate nothing (R2/R3/R4, INV-004).
* If a mutation succeeds but a later step fails, rollback retires only the owned
  resources and, if it cannot fully undo them, surfaces
  :class:`InitRollbackIncompleteError` *in addition to* the original cause so a
  partial state is never reported as success (R11/R12, INV-005/INV-006).

The service never prints; it returns an :class:`InitOutcome` the CLI renders
(handlers-do-not-print contract).  No network side effects occur (R17).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.loader import resolve_project_config
from ..config.models import ResolvedProjectConfig
from ..config.target import build_target_normalizer, build_workspace_naming
from ..git.lifecycle import GitWriter
from ..git.repository import GitRepository
from .errors import (
    BranchAlreadyExistsError,
    DerivedWorktreePathInvalidError,
    GitCommandError,
    InitGitOperationFailedError,
    InitPostconditionFailedError,
    InitRollbackIncompleteError,
    WorkspaceAlreadyExistsError,
    WorktreeAlreadyRegisteredError,
    WorktreePathAlreadyExistsError,
)
from .naming import ResolvedWorkspaceIdentity
from .worktree import WorkspaceObserver


@dataclass(frozen=True, slots=True)
class InitOutcome:
    """Structured, transport-neutral result of a successful ``init`` (R10).

    Exposes at least ``target``, ``branch``, ``worktree_path`` and
    ``base_branch`` (R10).  ``base_commit`` records the resolved base ref the
    branch was created from, useful for diagnostics and later specs.
    """

    target: str
    branch: str
    worktree_path: Path
    base_branch: str
    base_commit: str

    def render_lines(self) -> str:
        """Render a stable, human/machine-friendly success summary (R10, R16).

        Only the product's own structured fields are emitted; raw Git output is
        never mixed in (R16).
        """

        return "\n".join(
            (
                f"target: {self.target}",
                f"branch: {self.branch}",
                f"worktree: {self.worktree_path}",
                f"base_branch: {self.base_branch}",
            )
        )


class InitWorkspaceService:
    """Orchestrate ``ramalio init`` outside the CLI (7.1, T1).

    Dependencies are injectable for testing: a resolved configuration, a
    read-only :class:`GitRepository`, an observer and a :class:`GitWriter`.  When
    omitted they are built from the execution directory, keeping the production
    path a one-liner while unit tests can inject fakes/spies.
    """

    def __init__(
        self,
        config: ResolvedProjectConfig,
        *,
        repository: GitRepository | None = None,
        observer: WorkspaceObserver | None = None,
        writer: GitWriter | None = None,
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
        self._writer = (
            writer if writer is not None else GitWriter(config.repository_root)
        )
        if registry is None:
            from ..capabilities import default_registry

            registry = default_registry()
        self._registry = registry
        self._lock_manager = lock_manager

    # --- public entry points ---------------------------------------------

    @classmethod
    def from_directory(cls, start: Path | str | None = None) -> "InitWorkspaceService":
        """Build the service by resolving configuration from ``start`` (T2).

        Configuration resolution raises the E1 configuration/state errors
        directly, so a broken project surfaces before any Git work begins.
        """

        config = resolve_project_config(start)
        return cls(config)

    def run(self, raw_target: str) -> InitOutcome:
        """Execute the full init pipeline for ``raw_target`` (7.1).

        The whole mutable pipeline runs under the per-target lifecycle lock so
        two concurrent inits of the same target cannot race (E7-S1 R3); distinct
        targets are unaffected (R4).
        """

        from .locking import target_lifecycle_lock

        # Resolve the identity first so the lock key uses the canonical target.
        identity = self._resolve_identity(raw_target)
        with target_lifecycle_lock(
            self._config.repository_root,
            identity.target.value,
            operation="init",
            lock_manager=self._lock_manager,
        ):
            return self._run_locked(identity)

    def _run_locked(self, identity: ResolvedWorkspaceIdentity) -> InitOutcome:
        # E4-S0 R13 / E7 fail-closed: reject configuration that enables an
        # unknown capability *before* any Git mutation, so a typo in a
        # capability name fails the operation instead of silently leaving an
        # incomplete workspace.
        self._verify_capability_configuration(identity)

        base = self._repo.resolve_base_branch(self._config.project.base_branch)
        resolved_path = self._observer.resolve_worktree_path(identity)

        self._preflight(identity, resolved_path)

        # E7-S0 R1/R2: the WHOLE mutable pipeline runs inside ONE common
        # LifecycleTransaction and one try/except.  Every mutation — the
        # capability before_init hooks, the Git branch, the Git worktree and the
        # capability after_init hooks — is registered as its own owned,
        # separately-compensable step the moment it happens (no Git-specific
        # MutationJournal orchestrator underneath).  Compensation runs LIFO, so
        # a failure at any point undoes exactly what preceded it, in reverse.
        from ..hooks import HookContext, HookJournal, LifecycleEvent
        from ..capabilities.base import CapabilityContext
        from ..transactions import LifecycleTransaction, raise_if_unsafe

        hook_ctx = HookContext(
            capability_context=CapabilityContext(
                config=self._config, identity=identity
            ),
            operation="init",
        )
        hook_journal = HookJournal()
        runner = self._hook_runner()
        transaction = LifecycleTransaction("init")

        try:
            # before_init: a capability MAY mutate a compensable resource here;
            # it is registered as a transaction step so a later failure
            # compensates it too (R5/INV-03).
            runner.run_event(
                LifecycleEvent.BEFORE_INIT,
                hook_ctx,
                journal=hook_journal,
                transaction=transaction,
            )

            # Create branch + worktree, each recorded as its own transaction
            # step at creation time (E7-S0 R2).
            self._create(identity, resolved_path, base_branch=base.name, transaction=transaction)

            # Verify the workspace is coherent; a failure compensates the whole
            # transaction LIFO (worktree, then branch, then capabilities).
            self._verify_postconditions(identity, resolved_path, base=base)

            # after_init: capability failures compensate everything LIFO while
            # preserving the original cause (E7-S0 R5/R7).
            runner.run_event(
                LifecycleEvent.AFTER_INIT,
                hook_ctx,
                journal=hook_journal,
                transaction=transaction,
            )
        except BaseException as exc:  # includes KeyboardInterrupt (R14)
            outcome = transaction.rollback(exc)
            # E7-S0 R6/R7/R16: surface a partial/unsafe rollback instead of
            # discarding the TransactionOutcome; otherwise re-raise the original
            # cause (which is preserved as the chained cause).
            raise_if_unsafe(outcome, operation="init")
            raise

        return InitOutcome(
            target=identity.target.value,
            branch=identity.branch_name,
            worktree_path=resolved_path,
            base_branch=base.name,
            base_commit=base.commit,
        )

    def _hook_runner(self):
        from ..hooks import HookRunner

        return HookRunner(self._registry)

    # --- pipeline steps ---------------------------------------------------

    def _resolve_identity(self, raw_target: str) -> ResolvedWorkspaceIdentity:
        """Normalize + validate the target and derive its identity (R1, T2).

        No inference from the current branch or history: the target comes only
        from the explicit argument (R1).
        """

        normalizer = build_target_normalizer(self._config)
        result = normalizer.normalize(raw_target)
        naming = build_workspace_naming(self._config)
        return naming.resolve(result.target)

    def _preflight(
        self, identity: ResolvedWorkspaceIdentity, resolved_path: Path
    ) -> None:
        """Validate all preconditions before mutating anything (R2-R5, T3).

        Fails closed: any collision raises and no resource is created
        (INV-004).  Idempotency is handled first: when both the branch and its
        worktree already exist and correspond, the workspace is considered
        already created and reported as :class:`WorkspaceAlreadyExistsError`
        rather than a partial per-resource collision (R14).
        """

        # E7-S2 R3/R2/R4/R5: the derived worktree path must resolve, symlink-
        # aware, inside the authorized boundary and never onto a protected root,
        # *before* any Git mutation happens.  A symlink inside the boundary that
        # points outside cannot authorize creating a worktree out of bounds
        # (AC-02).  This runs first so a boundary escape fails closed with no
        # branch/worktree created (INV-004).
        self._validate_boundary(identity, resolved_path)

        branch = identity.branch_name

        branch_exists = self._repo.branch_exists(branch)
        registered = self._repo.get_worktree_by_path(resolved_path)

        # R14 idempotency: a prior successful init already produced both the
        # branch and its worktree at the derived path with that branch checked
        # out.  A second identical init must fail controlled, not duplicate.
        if (
            branch_exists
            and registered is not None
            and registered.branch == branch
        ):
            raise WorkspaceAlreadyExistsError(
                f"workspace for target '{identity.target.value}' already exists "
                f"(branch '{branch}' with worktree at {resolved_path}); "
                "nothing to create"
            )

        # R3: branch already exists (but not a full matching workspace). Guide
        # the user toward `adopt` without adopting automatically.
        if branch_exists:
            raise BranchAlreadyExistsError(
                f"branch '{branch}' already exists; init does not overwrite it. "
                "Use `adopt` if you intend to manage existing work."
            )

        # R4: path already registered as a (different) worktree.
        if registered is not None:
            raise WorktreeAlreadyRegisteredError(
                f"path {resolved_path} is already registered as a Git worktree "
                f"(branch '{registered.branch}'); init will not overwrite it."
            )

        # R4: path exists on disk but is not a registered worktree.
        if resolved_path.exists():
            raise WorktreePathAlreadyExistsError(
                f"path {resolved_path} already exists on disk; "
                "init will not overwrite it."
            )

    def _verify_capability_configuration(
        self, identity: ResolvedWorkspaceIdentity
    ) -> None:
        """Reject unknown/invalid capability configuration before mutating (R13).

        Delegates to :meth:`CapabilityRegistry.verify_configuration`, which
        raises :class:`CapabilityUnknownError` for an enabled-but-unregistered
        capability and :class:`CapabilityConfigInvalidError` for a bad
        namespaced config.  Running it before any Git work keeps ``init``
        fail-closed: a typo like ``[capabilities.mystery] enabled=true`` aborts
        the operation instead of leaving a half-created workspace.
        """

        from ..capabilities import verify_capability_configuration

        verify_capability_configuration(self._registry, self._config, identity)

    def _validate_boundary(
        self, identity: ResolvedWorkspaceIdentity, resolved_path: Path
    ) -> None:
        """Fail closed if the derived worktree path escapes the boundary (E7-S2).

        Uses the central :class:`SafePathResolver` so ``init`` shares the exact
        symlink-aware boundary rules ``destroy`` uses (R1/R3): the candidate is
        resolved against the real filesystem, collapsing ``..`` and symlinks,
        then compared against the authorized worktree boundary and protected
        roots (R2/R4/R5).  Raises :class:`WorktreePathAlreadyExistsError`'s
        sibling :class:`DerivedWorktreePathInvalidError` on escape so no Git
        mutation is attempted (INV-004).
        """

        from ..security import PathBoundaryPolicy, SafePathResolver
        from ..security.paths import PathBoundaryError

        resolver = SafePathResolver(
            PathBoundaryPolicy(
                repository_root=self._config.repository_root,
                worktree_directory=self._config.worktree.directory,
            )
        )
        try:
            resolver.validate_worktree_path(resolved_path)
        except PathBoundaryError as exc:
            raise DerivedWorktreePathInvalidError(
                f"refusing to create worktree for target "
                f"'{identity.target.value}': {exc}"
            ) from exc

    def _create(
        self,
        identity: ResolvedWorkspaceIdentity,
        resolved_path: Path,
        *,
        base_branch: str,
        transaction,
    ) -> None:
        """Create branch then worktree, recording each as its own compensable
        transaction step at creation time (R6, R7, E7-S0 R2, T4/T5).

        Two separate steps make ownership explicit: if the worktree step fails,
        the branch created by *this* execution is compensated LIFO by the
        transaction (R11, CT-07).  Each compensation re-observes Git and only
        ever retires a resource this execution owns (R13, 7.5).
        """

        # Step 1: create the branch from the resolved base ref (R6).
        try:
            self._writer.create_branch(branch=identity.branch_name, base=base_branch)
        except GitCommandError as exc:
            # Nothing owned yet; no rollback needed, surface the cause.
            raise InitGitOperationFailedError(
                f"failed to create branch '{identity.branch_name}' for target "
                f"'{identity.target.value}': {exc}"
            ) from exc

        branch_step = transaction.record_step(
            resource_type="git:branch",
            resource_identity=identity.branch_name,
            action="create",
            owned=True,
            compensation=lambda: self._undo_branch(identity),
        )
        transaction.mark_completed(branch_step)

        # Step 2: attach the worktree to the freshly-created branch (R7).
        try:
            self._writer.add_worktree_for_branch(
                branch=identity.branch_name, worktree_path=resolved_path
            )
        except GitCommandError as exc:
            # R11: the branch step is already recorded/completed. A failed
            # ``git worktree add`` may still have left a partial worktree at the
            # derived path; register a worktree compensation so the caller's
            # LIFO rollback retires that partial worktree BEFORE the branch,
            # then surface the original cause.
            partial_step = transaction.record_step(
                resource_type="git:worktree",
                resource_identity=str(resolved_path),
                action="create-partial",
                owned=True,
                compensation=lambda: self._undo_worktree(identity, resolved_path),
            )
            transaction.mark_completed(partial_step)
            raise InitGitOperationFailedError(
                f"failed to create worktree for target "
                f"'{identity.target.value}': {exc}"
            ) from exc

        worktree_step = transaction.record_step(
            resource_type="git:worktree",
            resource_identity=str(resolved_path),
            action="create",
            owned=True,
            compensation=lambda: self._undo_worktree(identity, resolved_path),
        )
        transaction.mark_completed(worktree_step)

    def _verify_postconditions(
        self,
        identity: ResolvedWorkspaceIdentity,
        resolved_path: Path,
        *,
        base,
    ) -> None:
        """Verify the created workspace is coherent before success (R9, T6).

        Checks: branch exists; worktree registered at the derived path; worktree
        uses the expected branch; worktree HEAD is a coherent commit.  Any
        incoherence raises :class:`InitPostconditionFailedError`; the caller's
        transaction rollback then compensates the branch/worktree steps LIFO
        (R12).
        """

        def fail(reason: str) -> None:
            raise InitPostconditionFailedError(
                f"post-creation verification failed for target "
                f"'{identity.target.value}': {reason}"
            )

        if not self._repo.branch_exists(identity.branch_name):
            fail(f"branch '{identity.branch_name}' was not created")

        worktree = self._repo.get_worktree_by_path(resolved_path)
        if worktree is None:
            fail(f"worktree at {resolved_path} is not registered")
            return  # pragma: no cover - fail() always raises

        if worktree.path != resolved_path:
            fail(
                f"registered worktree path {worktree.path} does not match "
                f"expected {resolved_path}"
            )

        if worktree.branch != identity.branch_name:
            fail(
                f"worktree uses branch '{worktree.branch}', "
                f"expected '{identity.branch_name}'"
            )

        if not worktree.head:
            fail("worktree HEAD does not resolve to a commit")

    # --- ownership-scoped compensations (transaction steps) --------------

    def _undo_worktree(
        self, identity: ResolvedWorkspaceIdentity, resolved_path: Path
    ) -> None:
        """Retire the worktree this execution created (R11, R13, T7).

        Re-observes Git before acting and only ever removes a worktree whose
        ownership is *demonstrable*: it must be registered at the derived path
        **and** check out exactly the branch this execution created (R13, 7.5).

        Fail-closed (H1): a detached worktree (``wt.branch is None``) is NOT
        owned by this init — a foreign/detached worktree may have appeared at
        the derived path while ``git worktree add`` partially failed, and E7-S0
        forbids destroying a resource we cannot prove we created.  Any branch
        mismatch, including a detached HEAD, therefore preserves the resource
        and raises :class:`InitRollbackIncompleteError` so the partial state
        stays diagnosable (INV-005/INV-006).  A missing worktree (step 2 failed
        before registering one) is a no-op.
        """

        wt = self._repo.get_worktree_by_path(resolved_path)
        if wt is None:
            return
        # Ownership must be demonstrable: require an exact branch match. A
        # detached worktree (branch is None) or a worktree on any other branch
        # is never removed by init's rollback.
        if wt.branch != identity.branch_name:
            observed = (
                f"branch '{wt.branch}'"
                if wt.branch is not None
                else "detached HEAD"
            )
            raise InitRollbackIncompleteError(
                f"rollback could not fully undo init for target "
                f"'{identity.target.value}'; leftover resources: worktree at "
                f"{resolved_path} ({observed}, ownership not demonstrable)"
            )
        try:
            self._writer.remove_worktree(resolved_path, force=True)
            self._writer.prune_worktrees()
        except GitCommandError as exc:
            raise InitRollbackIncompleteError(
                f"rollback could not fully undo init for target "
                f"'{identity.target.value}'; leftover resources: worktree at "
                f"{resolved_path}"
            ) from exc

    def _undo_branch(self, identity: ResolvedWorkspaceIdentity) -> None:
        """Delete the branch this execution created (R11, R13, T7).

        Only deletes if the branch still exists and is not (any longer) checked
        out in a worktree (R13).  Raises :class:`InitRollbackIncompleteError` if
        the owned branch cannot be retired (INV-006).
        """

        branch = identity.branch_name
        if not self._repo.branch_exists(branch):
            return
        in_use = self._repo.get_worktree_by_branch(branch)
        if in_use is not None:
            raise InitRollbackIncompleteError(
                f"rollback could not fully undo init for target "
                f"'{identity.target.value}'; leftover resources: branch "
                f"'{branch}' (still checked out at {in_use.path})"
            )
        try:
            self._writer.delete_branch(branch, force=True)
        except GitCommandError as exc:
            raise InitRollbackIncompleteError(
                f"rollback could not fully undo init for target "
                f"'{identity.target.value}'; leftover resources: branch "
                f"'{branch}'"
            ) from exc
