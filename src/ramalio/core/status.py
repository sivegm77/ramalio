"""Status lifecycle service: detailed, read-only workspace diagnosis (E3-S1).

``GetWorkspaceStatusService`` explains, for one target, the Git/local reality of
its workspace: expected identity vs observed reality, basic Git status,
conceptual state, an informative destroy-safety evaluation and a suggested
action.  It never mutates Git or the filesystem and never contacts a remote
(INV-01/INV-05, R16).

The result is intentionally extensible: it reserves an empty ``capabilities``
slot so E4 can add capability status without redesigning the identity/Git core
(INV-04, R14, 7.4).

Flow (7.1)::

    resolve identity
          -> observe branch/worktree (E2-S0)
          -> classify conceptual state
          -> observe git status when applicable
          -> evaluate destroy safety (reuse E2-S3 rules)
          -> derive suggested action
          -> return WorkspaceStatus

The service never prints; it returns a :class:`WorkspaceStatus` the CLI renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ..config.loader import resolve_project_config
from ..config.models import ResolvedProjectConfig
from ..config.target import build_target_normalizer, build_workspace_naming
from ..git.models import GitStatus
from ..git.repository import GitRepository
from .naming import ResolvedWorkspaceIdentity
from .worktree import ObservedWorkspace, WorkspaceObserver

if TYPE_CHECKING:
    from ..capabilities import CapabilityRegistry


class WorkspaceState(Enum):
    """Conceptual workspace state (R5).

    ``READY``/``DIRTY`` require a recognized, compatible workspace; the other
    states describe partial or anomalous realities that are never hidden
    (INV-03).
    """

    READY = "READY"
    DIRTY = "DIRTY"
    BRANCH_ONLY = "BRANCH_ONLY"
    MISSING = "MISSING"
    INCONSISTENT = "INCONSISTENT"
    DETACHED = "DETACHED"
    PRUNABLE = "PRUNABLE"


class SuggestedAction(Enum):
    """Conceptual next action; never executed automatically (R8)."""

    INIT = "init"
    ADOPT = "adopt"
    NONE = "none"
    INSPECT = "inspect"


# Stable, machine-readable reasons for non-normal states (R6).
REASON_BRANCH_NOT_FOUND = "BRANCH_NOT_FOUND"
REASON_WORKTREE_NOT_FOUND = "WORKTREE_NOT_FOUND"
REASON_WORKTREE_PATH_MISMATCH = "WORKTREE_PATH_MISMATCH"
REASON_WORKTREE_BRANCH_MISMATCH = "WORKTREE_BRANCH_MISMATCH"
REASON_BRANCH_IN_OTHER_WORKTREE = "BRANCH_IN_OTHER_WORKTREE"
REASON_WORKTREE_DETACHED = "WORKTREE_DETACHED"
REASON_WORKTREE_PRUNABLE = "WORKTREE_PRUNABLE"

# Destroy blocker reasons (informative; reuse E2-S3 semantics without executing).
BLOCKER_DIRTY_TRACKED = "DIRTY_TRACKED_CHANGES"
BLOCKER_UNTRACKED = "UNTRACKED_FILES"
BLOCKER_NOT_A_WORKSPACE = "NO_WORKTREE_TO_DESTROY"
BLOCKER_BRANCH_IN_OTHER_WORKTREE = "BRANCH_IN_OTHER_WORKTREE"
BLOCKER_PATH_MISMATCH = "WORKTREE_PATH_MISMATCH"
BLOCKER_DETACHED = "WORKTREE_DETACHED"
BLOCKER_PROTECTED_BASE_BRANCH = "PROTECTED_BASE_BRANCH"
BLOCKER_PRUNABLE = "WORKTREE_PRUNABLE"


@dataclass(frozen=True, slots=True)
class ExpectedIdentity:
    """Expected identity derived from the target and configuration (R2)."""

    target: str
    expected_branch: str
    expected_worktree_path: Path


@dataclass(frozen=True, slots=True)
class ObservedReality:
    """Observed Git reality for the target (R3)."""

    branch_exists: bool
    branch_checked_out_path: Path | None
    worktree_registered: bool
    worktree_branch: str | None
    worktree_head: str | None
    worktree_path_exists: bool


@dataclass(frozen=True, slots=True)
class GitStatusSummary:
    """Basic Git status for a compatible worktree (R4)."""

    clean: bool
    tracked_changes: bool
    untracked_changes: bool
    detached: bool


@dataclass(frozen=True, slots=True)
class DestroySafety:
    """Informative destroy-readiness evaluation (R7).

    Reuses E2-S3 rules conceptually but never executes destroy.  ``safe`` is
    ``True`` only when no blockers are present.
    """

    safe: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    """Structured, extensible status result (R12, R14)."""

    identity: ExpectedIdentity
    state: WorkspaceState
    observed: ObservedReality
    git: GitStatusSummary | None
    destroy_safety: DestroySafety
    suggested_action: SuggestedAction
    reason: str | None = None
    # Reserved for E4; always empty in E3 (INV-04, R14, 7.4).
    capabilities: tuple = field(default_factory=tuple)

    def render_lines(self) -> str:
        """Render a readable, human-friendly summary (R13)."""

        lines = [
            f"Target: {self.identity.target}",
            f"State: {self.state.value}",
        ]
        if self.reason is not None:
            lines.append(f"Reason: {self.reason}")
        lines.append(f"Expected branch: {self.identity.expected_branch}")
        lines.append(f"Expected worktree: {self.identity.expected_worktree_path}")
        if self.observed.worktree_branch is not None:
            lines.append(f"Branch: {self.observed.worktree_branch}")
        if self.git is not None:
            git_bits = []
            if self.git.tracked_changes:
                git_bits.append("tracked changes")
            if self.git.untracked_changes:
                git_bits.append("untracked files")
            if self.git.detached:
                git_bits.append("detached")
            summary = ", ".join(git_bits) if git_bits else "clean"
            lines.append(f"Git: {summary}")
        blockers = (
            ", ".join(self.destroy_safety.blockers)
            if self.destroy_safety.blockers
            else "none"
        )
        lines.append(
            f"Destroy safe: {'yes' if self.destroy_safety.safe else 'no'} "
            f"(blockers: {blockers})"
        )
        lines.append(f"Suggested action: {self.suggested_action.value}")
        if self.capabilities:
            lines.append("Capabilities:")
            for cap in self.capabilities:
                lines.append(f"  - {cap.name}: {cap.state.value} ({cap.summary})")
        return "\n".join(lines)


class GetWorkspaceStatusService:
    """Orchestrate ``ramalio status <target>`` outside the CLI (7.1, T1)."""

    def __init__(
        self,
        config: ResolvedProjectConfig,
        *,
        repository: GitRepository | None = None,
        observer: WorkspaceObserver | None = None,
        registry: "CapabilityRegistry | None" = None,
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
        # Optional capability registry (E4-S0). Defaults to the product registry
        # (empty in E4-S0), so status behaves exactly as in E3 when no
        # capability is registered.
        if registry is None:
            from ..capabilities import default_registry

            registry = default_registry()
        self._registry = registry

    # --- public entry points ---------------------------------------------

    @classmethod
    def from_directory(
        cls, start: Path | str | None = None
    ) -> "GetWorkspaceStatusService":
        config = resolve_project_config(start)
        return cls(config)

    def run(self, raw_target: str) -> WorkspaceStatus:
        """Produce a detailed, read-only status for ``raw_target`` (7.1)."""

        identity = self._resolve_identity(raw_target)
        observation = self._observer.observe(identity)

        expected = ExpectedIdentity(
            target=identity.target.value,
            expected_branch=identity.branch_name,
            expected_worktree_path=observation.resolved_worktree_path,
        )
        observed = self._observe_reality(identity, observation)
        state, reason = self._classify(identity, observation)
        git = self._git_summary(state, observation)
        destroy_safety = self._evaluate_destroy_safety(
            identity, observation, state
        )
        suggested = self._suggested_action(state)
        capabilities = self._collect_capabilities(identity)

        return WorkspaceStatus(
            identity=expected,
            state=state,
            observed=observed,
            git=git,
            destroy_safety=destroy_safety,
            suggested_action=suggested,
            reason=reason,
            capabilities=capabilities,
        )

    # --- identity ---------------------------------------------------------

    def _resolve_identity(self, raw_target: str) -> ResolvedWorkspaceIdentity:
        normalizer = build_target_normalizer(self._config)
        result = normalizer.normalize(raw_target)
        naming = build_workspace_naming(self._config)
        return naming.resolve(result.target)

    # --- observation ------------------------------------------------------

    def _observe_reality(
        self, identity: ResolvedWorkspaceIdentity, observation: ObservedWorkspace
    ) -> ObservedReality:
        """Collect the observed Git facts (R3)."""

        other = self._observer.branch_used_by_other_worktree(identity)
        branch_checked_out_path: Path | None = None
        if observation.worktree is not None and observation.branch_checked_out_here:
            branch_checked_out_path = observation.resolved_worktree_path
        elif other is not None:
            branch_checked_out_path = other.path

        return ObservedReality(
            branch_exists=observation.branch_exists,
            branch_checked_out_path=branch_checked_out_path,
            worktree_registered=observation.worktree is not None,
            worktree_branch=observation.worktree_branch,
            worktree_head=observation.worktree_head,
            worktree_path_exists=observation.resolved_worktree_path.exists(),
        )

    # --- classification (deterministic table, 7.3) -----------------------

    def _classify(
        self, identity: ResolvedWorkspaceIdentity, observation: ObservedWorkspace
    ) -> tuple[WorkspaceState, str | None]:
        """Classify the conceptual state and its reason (R5/R6, T2)."""

        registered = observation.worktree

        if registered is not None:
            # Prunable takes precedence: Git flags the entry or the path is gone.
            if registered.prunable or not observation.resolved_worktree_path.exists():
                return WorkspaceState.PRUNABLE, REASON_WORKTREE_PRUNABLE
            if registered.is_detached or registered.branch is None:
                return WorkspaceState.DETACHED, REASON_WORKTREE_DETACHED
            if registered.branch != identity.branch_name:
                return (
                    WorkspaceState.INCONSISTENT,
                    REASON_WORKTREE_BRANCH_MISMATCH,
                )
            # Compatible worktree at the canonical path.
            status = observation.git_status
            if status is not None and (status.dirty or status.untracked):
                return WorkspaceState.DIRTY, None
            return WorkspaceState.READY, None

        # No worktree registered at the canonical path.
        if not observation.branch_exists:
            return WorkspaceState.MISSING, None

        # Branch exists; is it checked out elsewhere?
        other = self._observer.branch_used_by_other_worktree(identity)
        if other is not None:
            return (
                WorkspaceState.INCONSISTENT,
                REASON_BRANCH_IN_OTHER_WORKTREE,
            )

        # Branch exists but no worktree and not checked out elsewhere: an
        # occupied canonical path is inconsistent; otherwise branch-only.
        if observation.resolved_worktree_path.exists():
            return WorkspaceState.INCONSISTENT, REASON_WORKTREE_PATH_MISMATCH
        return WorkspaceState.BRANCH_ONLY, None

    def _git_summary(
        self, state: WorkspaceState, observation: ObservedWorkspace
    ) -> GitStatusSummary | None:
        """Summarize Git status for a worktree that exists (R4)."""

        status: GitStatus | None = observation.git_status
        if status is None:
            return None
        return GitStatusSummary(
            clean=status.clean,
            tracked_changes=status.dirty,
            untracked_changes=status.untracked,
            detached=status.detached,
        )

    # --- destroy safety (reuse E2-S3 rules, informative only) ------------

    def _evaluate_destroy_safety(
        self,
        identity: ResolvedWorkspaceIdentity,
        observation: ObservedWorkspace,
        state: WorkspaceState,
    ) -> DestroySafety:
        """Evaluate destroy readiness without executing it (R7, 7.2).

        Mirrors the E2-S3 preconditions: base-branch protection, exact
        ownership, dirty/untracked local work, and anomalous states all block a
        safe destroy.  Never runs a mutation.
        """

        blockers: list[str] = []

        # Base branch protection (E2-S3 R14).
        if identity.branch_name == self._config.project.base_branch:
            blockers.append(BLOCKER_PROTECTED_BASE_BRANCH)

        if state is WorkspaceState.MISSING:
            blockers.append(BLOCKER_NOT_A_WORKSPACE)
        elif state is WorkspaceState.BRANCH_ONLY:
            # No worktree to remove; destroy would be branch-only, not the full
            # workspace teardown status is reporting readiness for.
            blockers.append(BLOCKER_NOT_A_WORKSPACE)
        elif state is WorkspaceState.PRUNABLE:
            blockers.append(BLOCKER_PRUNABLE)
        elif state is WorkspaceState.DETACHED:
            blockers.append(BLOCKER_DETACHED)
        elif state is WorkspaceState.INCONSISTENT:
            registered = observation.worktree
            if registered is not None and registered.branch != identity.branch_name:
                blockers.append(BLOCKER_PATH_MISMATCH)
            else:
                blockers.append(BLOCKER_BRANCH_IN_OTHER_WORKTREE)
        else:
            # READY or DIRTY: only local work blocks (E2-S3 R6/R7).
            status = observation.git_status
            if status is not None:
                if status.dirty:
                    blockers.append(BLOCKER_DIRTY_TRACKED)
                if status.untracked:
                    blockers.append(BLOCKER_UNTRACKED)

        return DestroySafety(safe=not blockers, blockers=tuple(blockers))

    # --- suggested action -------------------------------------------------

    def _suggested_action(self, state: WorkspaceState) -> SuggestedAction:
        """Derive the conceptual next action (R8)."""

        if state is WorkspaceState.MISSING:
            return SuggestedAction.INIT
        if state is WorkspaceState.BRANCH_ONLY:
            return SuggestedAction.ADOPT
        if state in (WorkspaceState.READY, WorkspaceState.DIRTY):
            return SuggestedAction.NONE
        # INCONSISTENT / DETACHED / PRUNABLE.
        return SuggestedAction.INSPECT

    # --- capabilities (E4-S0) --------------------------------------------

    def _collect_capabilities(
        self, identity: ResolvedWorkspaceIdentity
    ) -> tuple:
        """Collect enabled-capability statuses via the registry (E4-S0 R9/R10).

        A capability failing to report status is surfaced as ERROR by the
        registry's error boundary, never collapsing the workspace status (R10).
        Empty when no capability is registered/enabled, keeping E3 behavior.
        """

        from ..capabilities import CapabilityContext

        context = CapabilityContext(config=self._config, identity=identity)
        # verify_configuration surfaces unknown/invalid capability config as a
        # stable product error before status is reported (R12/R13).
        self._registry.verify_configuration(context)
        return self._registry.collect_status(context)
