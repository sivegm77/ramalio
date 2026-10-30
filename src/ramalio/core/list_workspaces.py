"""List lifecycle service: aggregate view of managed workspaces (E3-S0).

``ListWorkspacesService`` answers the operational question "which workspaces
exist in this project and what is their basic condition?" without turning
ramalio into a registry parallel to Git (spec 2, INV-01/INV-05).

Git remains the authority for branches and worktrees; the project configuration
remains the authority for naming.  This service is strictly read-only: it never
prunes, removes, deletes or fetches (INV-04, R16).

Flow (7.1)::

    resolve project
          -> list Git worktrees (E2-S0 authority)
          -> classify main checkout vs additional worktrees
          -> for each additional worktree: derive/validate identity,
             corroborate branch + path, observe basic status
          -> classify anomalies (detached / prunable / inconsistent /
             unrecognized)
          -> sort deterministically
          -> return structured list

The service never prints; it returns a :class:`WorkspaceListing` the CLI renders
(handlers-do-not-print contract).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from ..config.loader import resolve_project_config
from ..config.models import ResolvedProjectConfig
from ..config.target import build_target_validator, build_workspace_naming
from ..core.errors import RamalioError
from ..git.models import WorktreeInfo
from ..git.repository import GitRepository
from .target import Target


class WorkspaceState(Enum):
    """Basic operational state of a listed worktree (R10).

    ``READY``/``DIRTY`` only apply when the identity is recognized.  The
    anomaly states are observable facts, never silently hidden (INV-03).
    """

    READY = "READY"
    DIRTY = "DIRTY"
    DETACHED = "DETACHED"
    PRUNABLE = "PRUNABLE"
    INCONSISTENT = "INCONSISTENT"
    UNRECOGNIZED = "UNRECOGNIZED"


@dataclass(frozen=True, slots=True)
class WorkspaceListItem:
    """A single entry in the managed-workspace listing (7.2).

    ``target``/``branch`` are absent when they cannot be derived unambiguously
    (INV-02).  ``recognized`` records whether the entry maps to a managed
    target.  ``reason`` carries a stable, machine-readable detail for anomalies
    (e.g. ``WORKTREE_PATH_MISMATCH``).
    """

    path: Path
    state: WorkspaceState
    recognized: bool
    target: str | None = None
    branch: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceListing:
    """Structured result produced before any CLI rendering (R15)."""

    items: tuple[WorkspaceListItem, ...]

    @property
    def has_managed_workspaces(self) -> bool:
        return bool(self.items)

    def render_lines(self) -> str:
        """Render a compact, terminal-friendly table (R14).

        When there are no additional workspaces, a clear single line is emitted
        instead of an empty table (R13).
        """

        if not self.items:
            return "No managed workspaces found."

        header = f"{'TARGET':<30} {'STATE':<13} {'BRANCH':<30} PATH"
        rows = [header]
        for item in self.items:
            target = item.target if item.target is not None else "-"
            branch = item.branch if item.branch is not None else "-"
            rows.append(
                f"{target:<30} {item.state.value:<13} {branch:<30} {item.path}"
            )
        return "\n".join(rows)


class ListWorkspacesService:
    """Orchestrate ``ramalio list`` outside the CLI (7.1, T3).

    Dependencies are injectable for testing, mirroring the other lifecycle
    services.  When omitted they are built from the execution directory.
    """

    def __init__(
        self,
        config: ResolvedProjectConfig,
        *,
        repository: GitRepository | None = None,
    ) -> None:
        self._config = config
        self._repo = (
            repository
            if repository is not None
            else GitRepository.from_root(config.repository_root)
        )
        self._validator = build_target_validator(config)
        self._naming = build_workspace_naming(config)
        self._branch_matcher = _BranchPatternMatcher(config.branch.pattern)

    # --- public entry points ---------------------------------------------

    @classmethod
    def from_directory(
        cls, start: Path | str | None = None
    ) -> "ListWorkspacesService":
        """Build the service by resolving configuration from ``start`` (R2)."""

        config = resolve_project_config(start)
        return cls(config)

    def run(self) -> WorkspaceListing:
        """Enumerate and classify managed workspaces (7.1)."""

        root = self._repo.get_root()
        worktrees = self._repo.list_worktrees()

        items: list[WorkspaceListItem] = []
        for wt in worktrees:
            # R4: the main checkout is the repository root itself; never present
            # it as a managed target.
            if self._is_main_checkout(wt, root):
                continue
            items.append(self._classify(wt))

        return WorkspaceListing(items=tuple(self._sort(items)))

    # --- classification ---------------------------------------------------

    def _is_main_checkout(self, wt: WorktreeInfo, root: Path) -> bool:
        """Whether ``wt`` is the repository's primary checkout (R4)."""

        return wt.path == root or wt.bare

    def _classify(self, wt: WorktreeInfo) -> WorkspaceListItem:
        """Classify a single additional worktree into a listing item (T6).

        Anomalies are reported per item and never abort the whole listing
        (7.4).  Order of checks is conservative: filesystem/registry anomalies
        first, then identity recognition.
        """

        # R9: prunable or missing path -> report, never prune.
        if wt.prunable or not wt.path.exists():
            return WorkspaceListItem(
                path=wt.path,
                state=WorkspaceState.PRUNABLE,
                recognized=False,
                reason="WORKTREE_PRUNABLE",
            )

        # R8: detached worktree -> no invented target.
        if wt.is_detached or wt.branch is None:
            return WorkspaceListItem(
                path=wt.path,
                state=WorkspaceState.DETACHED,
                recognized=False,
                reason="WORKTREE_DETACHED",
            )

        # R5: attempt a reversible, unambiguous target derivation from the
        # branch name, then validate through E1-S1.
        target = self._recognize_target(wt.branch)
        if target is None:
            return WorkspaceListItem(
                path=wt.path,
                state=WorkspaceState.UNRECOGNIZED,
                recognized=False,
                branch=wt.branch,
                reason="BRANCH_NAME_UNRECOGNIZED",
            )

        # R6/R7: corroborate the branch-derived identity against the expected
        # canonical path; a contradiction is inconsistent, not silently fixed.
        expected_path = self._expected_path(target)
        if expected_path is None or wt.path != expected_path:
            return WorkspaceListItem(
                path=wt.path,
                state=WorkspaceState.INCONSISTENT,
                recognized=False,
                target=target.value,
                branch=wt.branch,
                reason="WORKTREE_PATH_MISMATCH",
            )

        # Recognized workspace: distinguish READY vs DIRTY (R11).
        state = self._basic_state(wt)
        return WorkspaceListItem(
            path=wt.path,
            state=state,
            recognized=True,
            target=target.value,
            branch=wt.branch,
        )

    def _recognize_target(self, branch: str) -> Target | None:
        """Derive a target from ``branch`` if reversible and valid (R5, 7.3).

        Returns ``None`` when the branch does not match the configured pattern
        or the extracted candidate is not a valid target (INV-02).
        """

        candidate = self._branch_matcher.extract(branch)
        if candidate is None:
            return None
        try:
            return self._validator.validate(candidate)
        except RamalioError:
            return None

    def _expected_path(self, target: Target) -> Path | None:
        """Resolve the canonical worktree path for ``target`` (R6)."""

        try:
            relative: PurePosixPath = self._naming.derive_worktree_path(target)
        except RamalioError:
            return None
        root = self._repo.get_root()
        combined = root / Path(*relative.parts)
        try:
            return combined.resolve()
        except OSError:  # pragma: no cover - defensive
            return combined.absolute()

    def _basic_state(self, wt: WorktreeInfo) -> WorkspaceState:
        """Observe READY vs DIRTY for a recognized worktree (R11).

        Dirtiness includes untracked files, consistent with the safety-oriented
        status model reused across the product.
        """

        status = self._repo.get_status(wt.path)
        if status.dirty or status.untracked:
            return WorkspaceState.DIRTY
        return WorkspaceState.READY

    # --- ordering ---------------------------------------------------------

    def _sort(self, items: list[WorkspaceListItem]) -> list[WorkspaceListItem]:
        """Deterministic order: recognized targets ascending, then others by
        path (R12)."""

        def key(item: WorkspaceListItem) -> tuple:
            # Recognized (target present) sort first, alphabetically by target;
            # unrecognized entries follow, ordered by path for stability.
            if item.target is not None and item.recognized:
                return (0, item.target, str(item.path))
            return (1, str(item.path), item.target or "")

        return sorted(items, key=key)


class _BranchPatternMatcher:
    """Reverse mapping for the single supported ``{target}`` branch pattern (7.3).

    Builds a regex from the configured pattern by escaping literals and turning
    the ``{target}`` placeholder into a capture group.  This is not a general
    heuristic: it inverts exactly the deterministic forward derivation from
    E1-S2 for patterns based on ``{target}``.
    """

    _PLACEHOLDER = "{target}"

    def __init__(self, pattern: str) -> None:
        self._pattern = pattern
        self._regex = self._compile(pattern)

    @classmethod
    def _compile(cls, pattern: str) -> re.Pattern[str] | None:
        # Only patterns containing exactly one {target} placeholder are
        # reversible without ambiguity in E3 (7.3).
        if pattern.count(cls._PLACEHOLDER) != 1:
            return None
        prefix, suffix = pattern.split(cls._PLACEHOLDER, 1)
        # A non-greedy capture keeps the mapping unambiguous when literal
        # separators surround the target.
        regex = f"^{re.escape(prefix)}(.+){re.escape(suffix)}$"
        try:
            return re.compile(regex)
        except re.error:  # pragma: no cover - defensive
            return None

    def extract(self, branch: str) -> str | None:
        """Return the target candidate captured from ``branch`` or ``None``."""

        if self._regex is None:
            return None
        match = self._regex.fullmatch(branch)
        if match is None:
            return None
        return match.group(1)
