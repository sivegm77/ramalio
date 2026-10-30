"""Destroy lifecycle service: safely close a managed workspace (E2-S3).

``DestroyWorkspaceService`` retires a Git worktree and, only when policy and
safety allow, its associated branch.  ``destroy`` never means "delete" blindly:
it protects against accidental loss of local work (spec 2, INV-01).  In E2 there
are no capabilities, so this operates purely on Git/worktree and branch cleanup
(out of scope 4.2, INV-07).

Flow (7.1)::

    resolve identity
          -> observe state
          -> validate exact ownership
          -> check dirty/untracked (fail closed)
          -> remove worktree (Git as primary mechanism)
          -> verify removal
          -> optional non-force branch deletion (opt-in policy)
          -> verify final state
          -> return result

Safety design:

* Fail-closed preflight: dirty tracked changes and untracked files block before
  any mutation (R6/R7, INV-01).
* Exact identity: only the worktree at the canonical path using the derived
  branch can be removed (R4/R5, INV-02).
* Never a global cleanup (INV-03); never ``git branch -D`` in the normal flow
  (R13); never a remote effect (R20).
* Branch deletion is opt-in and secondary to worktree removal.  A branch that is
  unsafe to delete is preserved with a reason -- a controlled partial closure,
  never data loss (R13/R17, 7.2).

The service never prints; it returns a :class:`DestroyOutcome` the CLI renders
(handlers-do-not-print contract).
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
    DestroyBlockedDirtyError,
    DestroyBranchInOtherWorktreeError,
    DestroyPostconditionFailedError,
    DestroyProtectedBranchError,
    DestroyWorktreeMismatchError,
    DestroyWorktreeRemoveFailedError,
    GitCommandError,
    WorkspaceNotFoundError,
)
from .naming import ResolvedWorkspaceIdentity
from .worktree import ObservedWorkspace, WorkspaceObserver

# Stable reasons a branch may be preserved rather than deleted (R18).
_REASON_POLICY_DISABLED = "policy-disabled"
_REASON_NOT_SAFE = "not-safe-to-delete"
_REASON_NO_WORKTREE = "branch-only-preserved"


@dataclass(frozen=True, slots=True)
class DestroyOutcome:
    """Structured, transport-neutral result of a ``destroy`` (R18).

    Exposes at least ``target``, ``worktree_removed``, ``branch_deleted`` and,
    when the branch was preserved, ``branch_preserved_reason``.  A partial
    closure (worktree removed but branch preserved) is expressed here without
    implying data loss (7.2).
    """

    target: str
    branch: str
    worktree_removed: bool
    branch_deleted: bool
    branch_preserved_reason: str | None

    def render_lines(self) -> str:
        """Render a stable success summary (R18)."""

        lines = [
            f"target: {self.target}",
            f"branch: {self.branch}",
            f"worktree_removed: {'true' if self.worktree_removed else 'false'}",
            f"branch_deleted: {'true' if self.branch_deleted else 'false'}",
        ]
        if self.branch_preserved_reason is not None:
            lines.append(f"branch_preserved_reason: {self.branch_preserved_reason}")
        return "\n".join(lines)


class DestroyWorkspaceService:
    """Orchestrate ``ramalio destroy`` outside the CLI (7.1, T2).

    Dependencies are injectable for testing, mirroring the other lifecycle
    services.  When omitted they are built from the execution directory.
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
    def from_directory(
        cls, start: Path | str | None = None
    ) -> "DestroyWorkspaceService":
        """Build the service by resolving configuration from ``start`` (T2)."""

        config = resolve_project_config(start)
        return cls(config)

    def run(self, raw_target: str) -> DestroyOutcome:
        """Execute the full destroy pipeline for ``raw_target`` (7.1).

        The whole mutable pipeline runs under the per-target lifecycle lock so a
        concurrent init/adopt/destroy of the same target cannot race (E7-S1 R3);
        distinct targets are unaffected (R4).
        """

        from .locking import target_lifecycle_lock

        identity = self._resolve_identity(raw_target)
        with target_lifecycle_lock(
            self._config.repository_root,
            identity.target.value,
            operation="destroy",
            lock_manager=self._lock_manager,
        ):
            return self._run_locked(identity)

    def _run_locked(self, identity: ResolvedWorkspaceIdentity) -> DestroyOutcome:
        # E4-S0 R13 fail-closed: reject unknown/invalid capability configuration
        # before observing or mutating anything, uniformly with init/adopt/
        # start/stop.
        from ..capabilities import verify_capability_configuration

        verify_capability_configuration(self._registry, self._config, identity)

        # R14: guard a misconfigured identity that collides with the base branch
        # before doing anything else.
        if identity.branch_name == self._config.project.base_branch:
            raise DestroyProtectedBranchError(
                f"derived branch '{identity.branch_name}' is the project base "
                f"branch; destroy will never remove it."
            )

        observation = self._observer.observe(identity)
        registered = observation.worktree

        # R2/R3: nothing to destroy vs. branch-only partial state.
        if registered is None and not observation.branch_exists:
            raise WorkspaceNotFoundError(
                f"no managed workspace found for target "
                f"'{identity.target.value}' (no branch and no worktree)."
            )

        if registered is None:
            # R3: branch exists but no worktree at the canonical path.
            return self._destroy_branch_only(identity, observation)

        # A worktree is registered at the canonical path.
        return self._destroy_full(identity, observation, registered)

    # --- identity ---------------------------------------------------------

    def _resolve_identity(self, raw_target: str) -> ResolvedWorkspaceIdentity:
        """Normalize + validate the target and derive its identity (R1)."""

        normalizer = build_target_normalizer(self._config)
        result = normalizer.normalize(raw_target)
        naming = build_workspace_naming(self._config)
        return naming.resolve(result.target)

    # --- branch-only path (R3) -------------------------------------------

    def _destroy_branch_only(
        self, identity: ResolvedWorkspaceIdentity, observation: ObservedWorkspace
    ) -> DestroyOutcome:
        """Handle a partial state: branch exists but no worktree (R3).

        No worktree is removed.  Branch cleanup is evaluated only when safe and
        opted-in; otherwise the branch is preserved with a reason.  The result
        distinguishes this case rather than pretending a full workspace existed.
        """

        # R5: the branch may be checked out in another worktree path.
        other = self._observer.branch_used_by_other_worktree(identity)
        if other is not None:
            raise DestroyBranchInOtherWorktreeError(
                f"branch '{identity.branch_name}' is checked out in a worktree "
                f"at {other.path}; destroy will not remove that worktree."
            )

        branch_deleted, reason = self._maybe_delete_branch(
            identity, worktree_removed=False
        )
        if not branch_deleted and reason is None:
            reason = _REASON_NO_WORKTREE

        self._verify_final_state(
            identity,
            expect_worktree_removed=False,
            expect_branch_deleted=branch_deleted,
        )

        return DestroyOutcome(
            target=identity.target.value,
            branch=identity.branch_name,
            worktree_removed=False,
            branch_deleted=branch_deleted,
            branch_preserved_reason=None if branch_deleted else reason,
        )

    # --- full path (worktree present) ------------------------------------

    def _destroy_full(
        self,
        identity: ResolvedWorkspaceIdentity,
        observation: ObservedWorkspace,
        registered,
    ) -> DestroyOutcome:
        """Remove the canonical worktree then optionally delete the branch (R15).

        Ownership is verified exactly, dirty/untracked state blocks before any
        mutation, and branch deletion is attempted only after the worktree
        removal is verified.
        """

        canonical = observation.resolved_worktree_path

        # R4: the canonical path must use the derived branch.
        if registered.branch != identity.branch_name:
            found = registered.branch if registered.branch is not None else "detached"
            raise DestroyWorktreeMismatchError(
                f"worktree at {canonical} uses branch '{found}', expected "
                f"'{identity.branch_name}'; destroy will not remove it."
            )

        # R5: the branch must not be checked out at a different path too. (For a
        # single-branch checkout this cannot happen, but guard defensively.)
        other = self._observer.branch_used_by_other_worktree(identity)
        if other is not None:
            raise DestroyBranchInOtherWorktreeError(
                f"branch '{identity.branch_name}' is also checked out in a "
                f"worktree at {other.path}; destroy will not remove it."
            )

        # R6/R7: dirty tracked changes and untracked files block before mutating
        # (INV-01).  Reuse the E2-S0 status observation (7.3).
        status = observation.git_status
        if status is not None:
            if status.dirty:
                raise DestroyBlockedDirtyError(
                    f"worktree at {canonical} has uncommitted tracked changes; "
                    "destroy is blocked to avoid losing local work."
                )
            if status.untracked:
                raise DestroyBlockedDirtyError(
                    f"worktree at {canonical} has untracked files; destroy is "
                    "blocked to avoid losing potentially useful local work."
                )

        # E7-S2: never operate a destructive removal on an unverified path.
        # The canonical path must resolve inside the worktree boundary and must
        # not be a protected root (R12/AC-03).
        from ..security import PathBoundaryPolicy, SafePathResolver
        from ..security.paths import PathBoundaryError

        resolver = SafePathResolver(
            PathBoundaryPolicy(
                repository_root=self._config.repository_root,
                worktree_directory=self._config.worktree.directory,
            )
        )
        try:
            resolver.validate_destroy_target(canonical)
        except PathBoundaryError as exc:
            raise DestroyWorktreeMismatchError(
                f"refusing to destroy worktree at {canonical}: {exc}"
            ) from exc

        # R1 (E7-S0): destroy runs under the common LifecycleTransaction so its
        # capability teardown participates in the shared ownership-scoped,
        # LIFO-compensable mechanism.  The Git worktree removal itself is
        # irreversible and is recorded as a non-compensable (unsafe) step rather
        # than being artificially recreated on failure (R13, INV-03).
        from ..capabilities.base import CapabilityContext
        from ..hooks import (
            HookContext,
            HookJournal,
            HookRunner,
            LifecycleEvent,
        )
        from ..transactions import LifecycleTransaction

        runner = HookRunner(self._registry)
        hook_ctx = HookContext(
            capability_context=CapabilityContext(
                config=self._config, identity=identity
            ),
            operation="destroy",
        )
        hook_journal = HookJournal()
        transaction = LifecycleTransaction("destroy")

        # E7-S0 R1/R2: the whole destructive flow runs inside the transaction.
        # Any failure after a mutation triggers rollback so compensable
        # capability teardown is undone and irreversible steps (worktree/branch
        # removal) are surfaced as ROLLBACK_NOT_SAFE — never recreated (R13).
        try:
            # R11: before_destroy capability hooks run before removing the Git
            # worktree, so capabilities can retire/validate resources first. A
            # failure blocks destroy; the transaction rolls back what was done.
            runner.run_event(
                LifecycleEvent.BEFORE_DESTROY,
                hook_ctx,
                journal=hook_journal,
                transaction=transaction,
            )

            # Record the irreversible Git worktree removal as an owned step with
            # no compensation: on failure rollback classifies it NOT_SAFE and
            # never recreates it (R13).  It is marked completed only once the
            # removal + verification succeed.
            git_step = transaction.record_step(
                resource_type="git:workspace",
                resource_identity=identity.branch_name,
                action="remove",
                owned=True,
                compensation=None,
            )

            # R9/R15: remove the worktree using Git as the primary mechanism. No
            # --force in the normal flow, so Git refuses if local content would
            # be lost (defense in depth with the preflight above).
            try:
                self._writer.remove_worktree(canonical, force=False)
            except GitCommandError as exc:
                # R16: worktree removal failed -> do not attempt branch deletion.
                raise DestroyWorktreeRemoveFailedError(
                    f"failed to remove worktree at {canonical} for target "
                    f"'{identity.target.value}': {exc}"
                ) from exc

            # E7-S0 R2/R13: mark the irreversible mutation completed *as soon as
            # it succeeds*, before any further step that could itself fail. If
            # prune/verification below raises, the transaction must still know
            # this removal happened so rollback reports it as an unsafe
            # (irreversible) resource rather than silently omitting it.
            transaction.mark_completed(git_step)

            # Verify the worktree is no longer registered (R9).
            self._writer.prune_worktrees()
            if self._repo.get_worktree_by_path(canonical) is not None:
                raise DestroyPostconditionFailedError(
                    f"worktree at {canonical} is still registered after removal "
                    f"for target '{identity.target.value}'."
                )

            # Optional, secondary, opt-in branch deletion (R10-R13, R17).
            branch_deleted, reason = self._maybe_delete_branch(
                identity, worktree_removed=True
            )
            if branch_deleted:
                # E7-S0 R2: the branch deletion is an owned, irreversible
                # mutation; record it (no compensation) so a later failure is
                # classified NOT_SAFE rather than recreating the branch.
                branch_step = transaction.record_step(
                    resource_type="git:branch",
                    resource_identity=identity.branch_name,
                    action="delete",
                    owned=True,
                    compensation=None,
                )
                transaction.mark_completed(branch_step)

            self._verify_final_state(
                identity,
                expect_worktree_removed=True,
                expect_branch_deleted=branch_deleted,
            )

            # R12: after_destroy cleanup runs after the Git worktree is retired.
            runner.run_event(
                LifecycleEvent.AFTER_DESTROY,
                hook_ctx,
                journal=hook_journal,
                transaction=transaction,
            )
        except BaseException as exc:  # includes KeyboardInterrupt (R14)
            outcome = transaction.rollback(exc)
            # E7-S0 R6/R7/R16: surface a partial/unsafe rollback (e.g. the
            # irreversible Git removal already happened) instead of discarding
            # the TransactionOutcome.
            from ..transactions import raise_if_unsafe

            raise_if_unsafe(outcome, operation="destroy")
            raise

        return DestroyOutcome(
            target=identity.target.value,
            branch=identity.branch_name,
            worktree_removed=True,
            branch_deleted=branch_deleted,
            branch_preserved_reason=None if branch_deleted else reason,
        )

    # --- branch policy ----------------------------------------------------

    def _maybe_delete_branch(
        self, identity: ResolvedWorkspaceIdentity, *, worktree_removed: bool
    ) -> tuple[bool, str | None]:
        """Attempt an opt-in, non-force branch deletion (R10-R13, R17, T6).

        Returns ``(deleted, preserved_reason)``.  The branch is preserved
        (never force-deleted) when: the policy is disabled; the branch no longer
        exists; it is still checked out somewhere; or Git refuses a non-force
        delete because the branch is not integrated (R13).
        """

        if not self._config.branch.delete_on_destroy:
            return False, _REASON_POLICY_DISABLED

        branch = identity.branch_name

        # If it does not exist (e.g. already gone), there is nothing to delete.
        if not self._repo.branch_exists(branch):
            return False, None

        # R12: never delete a branch still checked out in some worktree.
        if self._repo.get_worktree_by_branch(branch) is not None:
            return False, _REASON_NOT_SAFE

        # R13: only a safe, non-force delete is allowed.  ``git branch -d``
        # refuses when the branch is not merged into its upstream/HEAD, which is
        # exactly the "not integrated" safety condition we require.
        try:
            self._writer.delete_branch(branch, force=False)
        except GitCommandError:
            # R17: preserve the branch, never force; report a partial closure.
            return False, _REASON_NOT_SAFE

        return True, None

    # --- verification -----------------------------------------------------

    def _verify_final_state(
        self,
        identity: ResolvedWorkspaceIdentity,
        *,
        expect_worktree_removed: bool,
        expect_branch_deleted: bool,
    ) -> None:
        """Verify the observable Git state matches the reported result (R7/R18).

        Fail-closed: if the registry/refs disagree with what we are about to
        report, raise :class:`DestroyPostconditionFailedError` so a partial
        state is never presented as a clean success (INV-07).
        """

        canonical = self._observer.resolve_worktree_path(identity)

        if expect_worktree_removed:
            if self._repo.get_worktree_by_path(canonical) is not None:
                raise DestroyPostconditionFailedError(
                    f"worktree at {canonical} is still registered for target "
                    f"'{identity.target.value}'."
                )

        if expect_branch_deleted:
            if self._repo.branch_exists(identity.branch_name):
                raise DestroyPostconditionFailedError(
                    f"branch '{identity.branch_name}' still exists after a "
                    f"reported deletion for target '{identity.target.value}'."
                )
