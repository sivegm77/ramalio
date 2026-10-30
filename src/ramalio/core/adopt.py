"""Adopt lifecycle service: incorporate existing work (E2-S2).

``AdoptWorkspaceService`` incorporates a *preexisting* branch/worktree into the
managed model without recreating it and without destroying useful local work
(spec 3, INV-01/INV-02).  Like ``init`` it depends on the E1 identity pipeline
and the read-only/mutating Git boundaries; from E10-S0 it also runs the
``after_adopt`` provisioning hooks (registry order) inside the common
:class:`LifecycleTransaction` so optional capabilities can finish the workspace
after the Git identity exists (E10-S0 R4/R5).  It never embeds concrete
provisioning logic itself (INV-07); Git-only projects observe no change (R1).

Flow (7.1)::

    resolve identity
          -> observe branch/worktree reality
          -> classify scenario
             * EXISTING_COMPATIBLE  -> after_adopt only (no Git mutation)
             * BRANCH_ONLY          -> create canonical worktree + after_adopt
             * conflict             -> fail conservatively, mutate nothing
          -> verify postconditions
          -> return adoption result

Safety design:

* Adoption is conservative: it only succeeds when Git reality is unambiguously
  compatible with the derived identity (spec 2, INV-03).
* Only a worktree *created by this execution* can ever be rolled back; the
  branch is preexisting and never part of rollback (7.3, R13, R15, INV-05).
* A dirty compatible worktree is preserved and reported, never cleaned or reset
  (R2/INV-02, R9).
* No network side effects occur (R16).

The service never prints; it returns an :class:`AdoptOutcome` the CLI renders
(handlers-do-not-print contract).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..config.loader import resolve_project_config
from ..config.models import ResolvedProjectConfig
from ..config.target import build_target_normalizer, build_workspace_naming
from ..git.lifecycle import GitWriter
from ..git.repository import GitRepository
from .errors import (
    AdoptBranchInOtherWorktreeError,
    AdoptBranchNotFoundError,
    AdoptGitOperationFailedError,
    AdoptPostconditionFailedError,
    AdoptRollbackIncompleteError,
    AdoptWorktreeBranchMismatchError,
    AdoptWorktreeDetachedError,
    AdoptWorktreePathConflictError,
    GitCommandError,
)
from .naming import ResolvedWorkspaceIdentity
from .worktree import ObservedWorkspace, WorkspaceObserver


class AdoptionScenario(Enum):
    """Explicit classification of the observed Git reality (7.2).

    Keeping the classification explicit (instead of scattered branching) makes
    the conservative decision auditable and directly testable (T2, T10).
    """

    EXISTING_COMPATIBLE = "existing-compatible"
    BRANCH_ONLY = "branch-only"
    BRANCH_MISSING = "branch-missing"
    BRANCH_OTHER_WORKTREE = "branch-other-worktree"
    PATH_CONFLICT = "path-conflict"
    BRANCH_MISMATCH = "branch-mismatch"
    DETACHED = "detached"


# Modes exposed in the successful result (R12).
_MODE_EXISTING = "existing-worktree"
_MODE_CREATED = "created-worktree"


@dataclass(frozen=True, slots=True)
class AdoptOutcome:
    """Structured, transport-neutral result of a successful ``adopt`` (R12).

    Exposes at least ``target``, ``branch``, ``worktree_path``,
    ``adoption_mode`` and ``git_dirty`` (R12).  ``adoption_mode`` is one of
    ``existing-worktree`` (nothing mutated) or ``created-worktree`` (only the
    canonical worktree was created for a preexisting branch).
    """

    target: str
    branch: str
    worktree_path: Path
    adoption_mode: str
    git_dirty: bool

    def render_lines(self) -> str:
        """Render a stable success summary (R12, INV-16-style output contract).

        Only the product's own structured fields are emitted; raw Git output is
        never mixed in.
        """

        return "\n".join(
            (
                f"target: {self.target}",
                f"branch: {self.branch}",
                f"worktree: {self.worktree_path}",
                f"adoption_mode: {self.adoption_mode}",
                f"git_dirty: {'true' if self.git_dirty else 'false'}",
            )
        )


class AdoptWorkspaceService:
    """Orchestrate ``ramalio adopt`` outside the CLI (7.1, T1).

    Dependencies are injectable for testing, mirroring
    :class:`~ramalio.core.init.InitWorkspaceService`: a resolved
    configuration, a read-only :class:`GitRepository`, an observer and a
    :class:`GitWriter`.  When omitted they are built from the execution
    directory.
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
    def from_directory(cls, start: Path | str | None = None) -> "AdoptWorkspaceService":
        """Build the service by resolving configuration from ``start`` (T1)."""

        config = resolve_project_config(start)
        return cls(config)

    def run(self, raw_target: str) -> AdoptOutcome:
        """Execute the full adopt pipeline for ``raw_target`` (7.1).

        The mutable pipeline runs under the per-target lifecycle lock so a
        concurrent init/adopt/destroy of the same target cannot race (E7-S1
        R3); distinct targets proceed in parallel (R4).
        """

        from .locking import target_lifecycle_lock

        identity = self._resolve_identity(raw_target)
        with target_lifecycle_lock(
            self._config.repository_root,
            identity.target.value,
            operation="adopt",
            lock_manager=self._lock_manager,
        ):
            return self._run_locked(identity)

    def _run_locked(self, identity: ResolvedWorkspaceIdentity) -> AdoptOutcome:
        # E4-S0 R13 / E7 fail-closed: reject configuration that enables an
        # unknown capability before observing or mutating anything.
        from ..capabilities import verify_capability_configuration

        verify_capability_configuration(self._registry, self._config, identity)

        observation = self._observer.observe(identity)
        scenario = self._classify(identity, observation)

        if scenario is AdoptionScenario.EXISTING_COMPATIBLE:
            return self._adopt_existing(identity, observation)
        if scenario is AdoptionScenario.BRANCH_ONLY:
            return self._adopt_branch_only(identity, observation)

        # Every remaining scenario is a conservative failure with no mutation.
        self._reject(identity, observation, scenario)
        raise AssertionError("unreachable")  # pragma: no cover - _reject always raises

    # --- identity ---------------------------------------------------------

    def _resolve_identity(self, raw_target: str) -> ResolvedWorkspaceIdentity:
        """Normalize + validate the target and derive its identity (R1).

        The target comes only from the explicit argument; ``adopt`` never infers
        a target from an incompatible branch name (out of scope 4.2, INV-03).
        """

        normalizer = build_target_normalizer(self._config)
        result = normalizer.normalize(raw_target)
        naming = build_workspace_naming(self._config)
        return naming.resolve(result.target)

    # --- classification ---------------------------------------------------

    def _classify(
        self, identity: ResolvedWorkspaceIdentity, observation: ObservedWorkspace
    ) -> AdoptionScenario:
        """Classify the observed reality against the derived identity (7.2, T2).

        The classification is conservative: any ambiguity resolves to a conflict
        scenario rather than a mutation (INV-01/INV-03).
        """

        # R4: no derived branch -> nothing to adopt.
        if not observation.branch_exists:
            return AdoptionScenario.BRANCH_MISSING

        canonical = observation.resolved_worktree_path
        registered = observation.worktree

        if registered is not None:
            # A worktree is registered at the canonical path.
            if registered.is_detached or registered.branch is None:
                # R8: detached worktree is incompatible with a branch identity.
                return AdoptionScenario.DETACHED
            if registered.branch != identity.branch_name:
                # R7: canonical path uses a different branch.
                return AdoptionScenario.BRANCH_MISMATCH
            # Branch + canonical worktree correspond exactly (R2).
            return AdoptionScenario.EXISTING_COMPATIBLE

        # No worktree registered at the canonical path.
        # R5: the branch may be checked out in *another* worktree path.
        other = self._observer.branch_used_by_other_worktree(identity)
        if other is not None:
            return AdoptionScenario.BRANCH_OTHER_WORKTREE

        # R6: the canonical path may be occupied by an ordinary directory or an
        # unrelated (unregistered) checkout on disk.
        if canonical.exists():
            return AdoptionScenario.PATH_CONFLICT

        # R3: branch exists, no worktree, path free -> branch-only adoptable.
        return AdoptionScenario.BRANCH_ONLY

    # --- success paths ----------------------------------------------------

    def _hook_runner(self):
        from ..hooks import HookRunner

        return HookRunner(self._registry)

    def _make_hook_context(self, identity: ResolvedWorkspaceIdentity):
        """Build the ``after_adopt`` hook context (E10-S0 R4/R5).

        Mirrors ``init``'s hook context: it wraps the capability context
        (project config + identity) and names the operation ``adopt`` so
        provisioning capabilities that react to ``after_adopt`` receive the same
        transport-neutral contract they receive for ``after_init``.
        """

        from ..hooks import HookContext
        from ..capabilities.base import CapabilityContext

        return HookContext(
            capability_context=CapabilityContext(
                config=self._config, identity=identity
            ),
            operation="adopt",
        )

    def _adopt_existing(
        self, identity: ResolvedWorkspaceIdentity, observation: ObservedWorkspace
    ) -> AdoptOutcome:
        """Adopt a fully-compatible existing branch+worktree, running provisioning
        (R2, R9, R14, E10-S0 R4/AC-03).

        Git identity is already compatible, so this call mutates no Git state.
        E10-S0 R4 still opens the common :class:`LifecycleTransaction` and runs
        the ``after_adopt`` hooks so optional provisioning capabilities can
        finish the workspace; adopt only returns success once those hooks
        complete.  Because Git was not mutated by this call, the transaction can
        only ever record capability mutations, and a hook failure compensates
        exactly those (never the preexisting worktree/branch — AC-05).

        A dirty compatible worktree is preserved and reported via ``git_dirty``
        (R9); dirtiness is never a failure here.
        """

        from ..hooks import HookJournal, LifecycleEvent
        from ..transactions import LifecycleTransaction, raise_if_unsafe

        dirty = self._is_dirty(observation)

        hook_ctx = self._make_hook_context(identity)
        hook_journal = HookJournal()
        runner = self._hook_runner()
        transaction = LifecycleTransaction("adopt")

        try:
            # after_adopt: capabilities run in registry order (E10-S0 R6).  A
            # failure compensates only capability mutations this call made
            # (there is no owned Git step here), preserving the preexisting
            # Git identity (AC-05).
            runner.run_event(
                LifecycleEvent.AFTER_ADOPT,
                hook_ctx,
                journal=hook_journal,
                transaction=transaction,
            )
        except BaseException as exc:  # includes KeyboardInterrupt
            outcome = transaction.rollback(exc)
            raise_if_unsafe(outcome, operation="adopt")
            raise

        return AdoptOutcome(
            target=identity.target.value,
            branch=identity.branch_name,
            worktree_path=observation.resolved_worktree_path,
            adoption_mode=_MODE_EXISTING,
            git_dirty=dirty,
        )

    def _validate_boundary(
        self, identity: ResolvedWorkspaceIdentity, resolved_path: Path
    ) -> None:
        """Fail closed if the canonical worktree path escapes the boundary (E7-S2).

        Shares the central symlink-aware :class:`SafePathResolver` used by
        ``init``/``destroy`` (R1/R3).  A boundary escape raises before any
        worktree is created, mutating nothing (INV-004/INV-01).
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
            raise AdoptWorktreePathConflictError(
                f"refusing to create worktree for target "
                f"'{identity.target.value}': {exc}"
            ) from exc

    def _adopt_branch_only(
        self, identity: ResolvedWorkspaceIdentity, observation: ObservedWorkspace
    ) -> AdoptOutcome:
        """Create only the canonical worktree for a preexisting branch (R3, R10,
        AC-02).

        No branch is created.  The new worktree checks out the existing branch
        at its current commit without altering any other checkout (R10).  If a
        later verification fails, only this worktree is rolled back; the branch
        is preserved (R13, R15).
        """

        resolved_path = observation.resolved_worktree_path

        # E7-S2 R3/R2/R4/R5: validate the canonical worktree path is inside the
        # authorized boundary (symlink-aware) *before* creating anything, so a
        # symlink escape cannot make adopt attach a worktree out of bounds
        # (AC-02, INV-004).
        self._validate_boundary(identity, resolved_path)

        # E7-S0 R1/R10: run the mutation under the common LifecycleTransaction.
        # ``adopt`` may only ever compensate resources *it* created, never the
        # preexisting branch (R10/R15); the worktree this execution attaches is
        # the sole owned Git step.  E10-S0 R5 adds the ``after_adopt``
        # provisioning hooks to that SAME transaction, so a hook failure rolls
        # back the worktree created by this call and compensates the
        # capabilities' own mutations LIFO — and nothing preexisting.
        from ..hooks import HookJournal, LifecycleEvent
        from ..transactions import LifecycleTransaction

        transaction = LifecycleTransaction("adopt")
        hook_ctx = self._make_hook_context(identity)
        hook_journal = HookJournal()
        runner = self._hook_runner()

        # Ensure the parent directory exists so `git worktree add` can create the
        # leaf checkout even when the configured worktree directory is new.
        parent = resolved_path.parent
        created_parent: Path | None = None
        if not parent.exists():
            created_parent = self._make_parents(parent)

        # The compensation removes only a worktree on our own branch and cleans
        # an empty parent we created; it never touches the preexisting branch.
        # Re-observing Git makes ownership demonstrable, so it is safe to run
        # even when ``git worktree add`` itself reported failure (H2).
        def _undo_worktree() -> None:
            self._rollback_worktree(
                identity,
                resolved_path,
                worktree_created=True,
                created_parent=created_parent,
                cause_code=None,
            )

        # E7-S0 R2 / H2: register the worktree step *before* invoking
        # ``git worktree add``.  A failed ``git worktree add`` is NOT a safe
        # "zero mutation" assumption: Git may have left a durable worktree
        # registered at the canonical path before exiting non-zero.  Recording
        # the compensation up front means the transaction's LIFO rollback
        # re-observes Git and retires exactly the worktree adopt created (if
        # any), while never touching the preexisting branch or a foreign
        # worktree on another branch (R13/R15).
        worktree_step = transaction.record_step(
            resource_type="git:worktree",
            resource_identity=identity.branch_name,
            action="create",
            owned=True,
            compensation=_undo_worktree,
        )
        transaction.mark_completed(worktree_step)

        # Run the mutation and the verification inside one try/except so BOTH a
        # ``git worktree add`` failure (which may have partially mutated) and a
        # postcondition failure compensate the transaction LIFO while preserving
        # the original cause (E7-S0 R5/R7).  KeyboardInterrupt is handled the
        # same way (R14).
        try:
            try:
                self._writer.add_worktree_for_branch(
                    branch=identity.branch_name, worktree_path=resolved_path
                )
            except GitCommandError as exc:
                raise AdoptGitOperationFailedError(
                    f"failed to create worktree for target "
                    f"'{identity.target.value}': {exc}"
                ) from exc

            self._verify_postconditions(identity, resolved_path)

            # after_adopt: provisioning capabilities run in registry order
            # (E10-S0 R6) inside the SAME transaction as the created worktree.
            # A hook failure compensates capability mutations and then the
            # worktree this call created, LIFO, while never touching the
            # preexisting branch (R5/AC-04).
            runner.run_event(
                LifecycleEvent.AFTER_ADOPT,
                hook_ctx,
                journal=hook_journal,
                transaction=transaction,
            )
        except BaseException as exc:
            outcome = transaction.rollback(exc)
            self._raise_for_rollback(identity, exc, outcome)
            raise

        # Observe once more to report dirty state of the freshly-attached
        # worktree (a branch-only worktree is normally clean, but report the
        # observed reality rather than assume).
        final_observation = self._observer.observe(identity)
        dirty = self._is_dirty(final_observation)

        return AdoptOutcome(
            target=identity.target.value,
            branch=identity.branch_name,
            worktree_path=resolved_path,
            adoption_mode=_MODE_CREATED,
            git_dirty=dirty,
        )

    def _raise_for_rollback(
        self,
        identity: ResolvedWorkspaceIdentity,
        primary: BaseException,
        outcome,
    ) -> None:
        """Surface a partial/unsafe rollback in addition to the primary cause.

        When the transaction could not fully compensate the worktree it created,
        raise :class:`AdoptRollbackIncompleteError` so a partial state stays
        diagnosable (E7-S0 R6/R16, INV-005/INV-006); otherwise let the caller
        re-raise the original postcondition failure.  ``cause_code`` carries the
        stable code of the original failure when available.
        """

        from ..transactions.transaction import RollbackOutcome

        if outcome.outcome in (RollbackOutcome.PARTIAL, RollbackOutcome.NOT_SAFE):
            cause_code = getattr(primary, "code", None)
            leftovers = ", ".join(outcome.rollback_errors or outcome.unsafe_resources)
            raise AdoptRollbackIncompleteError(
                f"rollback could not fully undo adopt for target "
                f"'{identity.target.value}'; leftover resources: {leftovers}",
                cause_code=cause_code,
            )

    # --- failure paths ----------------------------------------------------

    def _reject(
        self,
        identity: ResolvedWorkspaceIdentity,
        observation: ObservedWorkspace,
        scenario: AdoptionScenario,
    ) -> None:
        """Fail conservatively for a conflict scenario, mutating nothing (T6).

        Each conflict maps to a stable domain error with actionable context; no
        branch, worktree or filesystem path is modified (INV-01/INV-02/INV-06).
        """

        target = identity.target.value
        branch = identity.branch_name
        path = observation.resolved_worktree_path

        if scenario is AdoptionScenario.BRANCH_MISSING:
            raise AdoptBranchNotFoundError(
                f"no branch '{branch}' exists for target '{target}'; "
                "there is nothing to adopt. Use `init` to create a new workspace."
            )

        if scenario is AdoptionScenario.BRANCH_OTHER_WORKTREE:
            other = self._observer.branch_used_by_other_worktree(identity)
            other_path = other.path if other is not None else "another path"
            raise AdoptBranchInOtherWorktreeError(
                f"branch '{branch}' is already checked out in a worktree at "
                f"{other_path}, not the canonical path {path}; adopt will not "
                "move or delete it."
            )

        if scenario is AdoptionScenario.PATH_CONFLICT:
            raise AdoptWorktreePathConflictError(
                f"path {path} already exists on disk but is not the expected "
                f"managed worktree for target '{target}'; adopt will not modify "
                "it."
            )

        if scenario is AdoptionScenario.BRANCH_MISMATCH:
            registered = observation.worktree
            found = registered.branch if registered is not None else "unknown"
            raise AdoptWorktreeBranchMismatchError(
                f"worktree at {path} uses branch '{found}', expected "
                f"'{branch}' for target '{target}'."
            )

        if scenario is AdoptionScenario.DETACHED:
            raise AdoptWorktreeDetachedError(
                f"worktree at {path} has a detached HEAD and is not compatible "
                f"with the branch identity '{branch}' required for target "
                f"'{target}'."
            )

        raise AssertionError(  # pragma: no cover - defensive
            f"unhandled adoption scenario: {scenario}"
        )

    # --- verification -----------------------------------------------------

    def _verify_postconditions(
        self, identity: ResolvedWorkspaceIdentity, resolved_path: Path
    ) -> None:
        """Verify the adopted workspace is coherent (R11, T8).

        Checks: branch exists; worktree registered at the canonical path; that
        worktree uses the expected branch and resolves to a commit.  Any
        incoherence raises :class:`AdoptPostconditionFailedError`; the caller
        decides whether a rollback is warranted (only for created worktrees).
        """

        def fail(reason: str) -> None:
            raise AdoptPostconditionFailedError(
                f"post-adoption verification failed for target "
                f"'{identity.target.value}': {reason}"
            )

        if not self._repo.branch_exists(identity.branch_name):
            fail(f"branch '{identity.branch_name}' does not exist")

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

    # --- rollback (worktree only; never the branch) ----------------------

    def _rollback_worktree(
        self,
        identity: ResolvedWorkspaceIdentity,
        resolved_path: Path,
        *,
        worktree_created: bool,
        created_parent: Path | None,
        cause_code: str | None,
    ) -> None:
        """Retire only the worktree this execution created (R13, R15, T7).

        Safety (7.3): rollback re-observes Git and only removes a worktree at the
        canonical path that uses the identity's branch, so it never touches a
        preexisting worktree.  The preexisting branch is *never* deleted, not
        even during rollback (R15, INV-05).  If the owned worktree cannot be
        retired, :class:`AdoptRollbackIncompleteError` is raised so the partial
        state stays diagnosable (INV-006).
        """

        remaining: list[str] = []

        if worktree_created:
            wt = self._repo.get_worktree_by_path(resolved_path)
            if wt is not None:
                # Ownership must be *demonstrable*: only remove a worktree that
                # checks out exactly the branch this adopt attached.  A detached
                # worktree (``wt.branch is None``) is NOT owned by adopt — it may
                # have appeared at the canonical path while ``git worktree add``
                # partially failed — so it is preserved, never force-removed
                # (E7-S0 INV-01/INV-03, R10; mirrors init's fail-closed rule).
                if wt.branch != identity.branch_name:
                    observed = (
                        f"branch '{wt.branch}'"
                        if wt.branch is not None
                        else "detached HEAD"
                    )
                    remaining.append(
                        f"worktree at {resolved_path} "
                        f"({observed}, ownership not demonstrable)"
                    )
                else:
                    try:
                        self._writer.remove_worktree(resolved_path, force=True)
                        self._writer.prune_worktrees()
                    except GitCommandError:
                        remaining.append(f"worktree at {resolved_path}")

        # Best-effort: remove an empty parent directory we created ourselves.
        self._cleanup_created_parent(created_parent)

        if remaining:
            joined = ", ".join(remaining)
            raise AdoptRollbackIncompleteError(
                f"rollback could not fully undo adopt for target "
                f"'{identity.target.value}'; leftover resources: {joined}",
                cause_code=cause_code,
            )

    # --- small helpers ----------------------------------------------------

    @staticmethod
    def _is_dirty(observation: ObservedWorkspace) -> bool:
        """Whether the observed worktree has local modifications (R9).

        Untracked files also count as local work worth preserving, so both
        tracked modifications and untracked files mark the workspace dirty.
        """

        status = observation.git_status
        if status is None:
            return False
        return status.dirty or status.untracked

    @staticmethod
    def _make_parents(parent: Path) -> Path | None:
        """Create ``parent`` (and missing ancestors) and return the topmost
        directory this call created, for later best-effort cleanup.

        Returns ``None`` when nothing had to be created.
        """

        # Find the topmost missing ancestor so rollback can remove exactly what
        # this execution created and nothing preexisting.
        topmost_missing: Path | None = None
        probe = parent
        while not probe.exists():
            topmost_missing = probe
            if probe.parent == probe:  # pragma: no cover - filesystem root
                break
            probe = probe.parent

        parent.mkdir(parents=True, exist_ok=True)
        return topmost_missing

    @staticmethod
    def _cleanup_created_parent(created_parent: Path | None) -> None:
        """Remove a parent directory tree this execution created, if still empty.

        Never removes a directory that now contains anything other than empty
        subdirectories we created, keeping cleanup conservative (INV-02).
        """

        if created_parent is None:
            return
        # Only remove if the tree is empty (defensive: never delete real work).
        try:
            for path in sorted(created_parent.rglob("*"), reverse=True):
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
                else:
                    # Something unexpected lives here; stop and keep it.
                    return
            if created_parent.exists() and not any(created_parent.iterdir()):
                created_parent.rmdir()
        except OSError:  # pragma: no cover - best-effort cleanup
            pass
