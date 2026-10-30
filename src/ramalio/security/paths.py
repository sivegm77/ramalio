"""Canonical, symlink-aware path boundary validation (E7-S2).

Every mutable path must resolve inside an authorized boundary (R1/R2).  The
resolver collapses ``..`` and symlinks against the real filesystem before
comparing, so a symlink inside the boundary that points outside cannot authorize
an out-of-boundary write or destruction (R3/AC-02).  It also refuses paths that
resolve to protected roots: the repository root, the user home, the filesystem
root (R4).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PathBoundaryError(Exception):
    """A path fell outside its authorized boundary or hit a protected root."""


@dataclass(frozen=True, slots=True)
class PathBoundaryPolicy:
    """Defines the authorized boundary for derived paths (R2/R4)."""

    repository_root: Path
    worktree_directory: str

    def boundary(self) -> Path:
        """The absolute directory derived paths must stay within."""

        return (self.repository_root / self.worktree_directory).resolve()

    def protected_roots(self) -> tuple[Path, ...]:
        """Paths that must never be a derived worktree/destroy target (R4)."""

        roots = [
            self.repository_root.resolve(),
            Path.home().resolve(),
            Path(self.repository_root.anchor or "/").resolve(),
        ]
        return tuple(roots)


class SafePathResolver:
    """Resolves and validates candidate paths against a boundary (R1/R3)."""

    def __init__(self, policy: PathBoundaryPolicy) -> None:
        self._policy = policy

    def _real(self, path: Path) -> Path:
        # Resolve against the real filesystem, collapsing symlinks/`..`. On
        # missing leaves, resolve the nearest existing ancestor and re-append,
        # so a not-yet-created worktree is still boundary-checked (R3).
        try:
            return path.resolve()
        except OSError:  # pragma: no cover - defensive
            return path.absolute()

    def is_within_boundary(self, candidate: Path) -> bool:
        boundary = self._policy.boundary()
        real = self._real(candidate)
        if real == boundary:
            # The boundary directory itself is not a valid leaf workspace.
            return False
        return boundary in real.parents

    def validate_worktree_path(self, candidate: Path) -> Path:
        """Validate a derived worktree path and return its canonical form.

        Raises :class:`PathBoundaryError` on traversal escape, protected roots,
        or a symlink that escapes the boundary (R2/R3/R4/R5/AC-01/AC-02/AC-03).
        """

        real = self._real(candidate)

        # AC-02: the boundary directory itself must not escape the repository via
        # a symlink.  If ``worktree_directory`` resolves outside the repository
        # root, any path "inside" it is really outside the repo, so reject it
        # rather than trust a symlinked boundary.
        repo_real = self._policy.repository_root.resolve()
        boundary = self._policy.boundary()
        if boundary != repo_real and repo_real not in boundary.parents:
            raise PathBoundaryError(
                f"worktree boundary {boundary} resolves outside the repository "
                f"root {repo_real}; refusing to use a symlinked boundary"
            )

        for protected in self._policy.protected_roots():
            if real == protected:
                raise PathBoundaryError(
                    f"path {real} resolves to a protected root and cannot be used"
                )

        if not self.is_within_boundary(candidate):
            raise PathBoundaryError(
                f"path {real} is outside the authorized worktree boundary "
                f"{self._policy.boundary()}"
            )
        return real

    def validate_destroy_target(self, candidate: Path) -> Path:
        """Validate a path before a destructive operation (R12/AC-03).

        Same rules as a worktree path: must be inside the boundary and never a
        protected root.  Callers must combine this with resource ownership.
        """

        return self.validate_worktree_path(candidate)


def resolve_within_directory(base: Path, relative: str) -> Path:
    """Resolve ``relative`` under ``base`` and require it stays inside (E7-S2).

    Generic, symlink-aware boundary check for callers that operate within an
    arbitrary directory (e.g. a worktree) rather than the repository-root-scoped
    :class:`PathBoundaryPolicy`.  Collapses ``..`` and symlinks against the real
    filesystem: a symlink inside ``base`` that points outside can never
    authorize an out-of-boundary read/write/destroy (audit H2/H3).

    Raises :class:`PathBoundaryError` if the resolved candidate is not ``base``
    itself or a descendant of it.  Missing leaves are resolved against their
    nearest existing ancestor so a not-yet-created path is still checked.
    """

    base_real = base.resolve()
    candidate = base / relative
    try:
        real = candidate.resolve()
    except OSError:  # pragma: no cover - defensive
        real = candidate.absolute()
    if real != base_real and base_real not in real.parents:
        raise PathBoundaryError(
            f"path '{relative}' resolves to {real}, outside the authorized "
            f"boundary {base_real}"
        )
    return real
