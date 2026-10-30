"""Project discovery for ramalio.

Git is the authority for the real repository root (INV-010).  This module
derives the project context from the execution directory without assuming a
fixed absolute path or repository-specific environment variables (INV-03).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import NotInGitRepositoryError, OperationError

# Filename of the shared, versioned project configuration (R2).
PROJECT_CONFIG_FILENAME = ".ramalio.toml"


@dataclass(frozen=True, slots=True)
class Project:
    """Resolved project context derived from the execution directory.

    ``repository_root`` is the Git top-level directory.  ``config_path`` is the
    conventional location of the shared project configuration; its existence is
    not guaranteed here and is checked by the loader (R2).
    """

    repository_root: Path

    @property
    def config_path(self) -> Path:
        """Return the conventional ``.ramalio.toml`` path for this root."""

        return self.repository_root / PROJECT_CONFIG_FILENAME


def _git_executable() -> str:
    """Locate the ``git`` executable or fail with an operation error."""

    git = shutil.which("git")
    if git is None:
        raise OperationError("git executable was not found on PATH")
    return git


def discover_repository_root(start: Path | str | None = None) -> Path:
    """Return the Git repository root for ``start`` (defaults to cwd).

    Works from the root and from any nested subdirectory that tracks back to the
    same repository (R1, INV-03).  Raises :class:`NotInGitRepositoryError` when
    the directory is not part of a Git working tree.
    """

    base = Path(start) if start is not None else Path.cwd()
    base = base.resolve()

    git = _git_executable()
    try:
        completed = subprocess.run(
            [git, "-C", str(base), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - defensive, hard to trigger
        raise OperationError(f"failed to invoke git: {exc}") from exc

    if completed.returncode != 0:
        raise NotInGitRepositoryError(
            f"'{base}' is not inside a Git repository "
            "(ramalio derives the project root from Git)"
        )

    toplevel = completed.stdout.strip()
    if not toplevel:
        raise NotInGitRepositoryError(f"'{base}' is not inside a Git repository")

    return Path(toplevel).resolve()


def discover_project(start: Path | str | None = None) -> Project:
    """Resolve the :class:`Project` context from the execution directory."""

    return Project(repository_root=discover_repository_root(start))
