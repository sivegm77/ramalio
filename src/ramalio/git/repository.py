"""Repository abstraction: the centralized Git query surface (E2-S0 R1).

:class:`GitRepository` is the single place lifecycle code asks Git about the
repository root, refs, branches, worktrees and checkout status.  It owns all
parsing of Git's machine-readable output and returns the structured models from
:mod:`.models` (INV-02, R1, R13).

Everything here is read-only: no ref or worktree is created or removed
(INV-03) and no remote is contacted (R14).
"""

from __future__ import annotations

from pathlib import Path

from ..core.errors import (
    BaseBranchNotFoundError,
    GitRepositoryInvalidError,
)
from ..core.project import discover_repository_root
from .models import BranchRef, GitStatus, WorktreeInfo
from .runner import GitRunner


class GitRepository:
    """Centralized, read-only Git query boundary bound to one repository root.

    Build instances through :meth:`discover` (reusing the E1-S0 root resolution)
    or :meth:`from_root` when the root is already known.  A custom
    :class:`GitRunner` can be injected for testing.
    """

    def __init__(self, root: Path, *, runner: GitRunner | None = None) -> None:
        self._root = Path(root).resolve()
        self._runner = runner if runner is not None else GitRunner(self._root)

    # --- construction -----------------------------------------------------

    @classmethod
    def discover(
        cls, start: Path | str | None = None, *, runner: GitRunner | None = None
    ) -> "GitRepository":
        """Resolve the repository from ``start`` (defaults to cwd) via E1-S0 (R2).

        Reuses :func:`discover_repository_root`, so a non-repository context
        raises :class:`~ramalio.core.errors.NotInGitRepositoryError`
        before any Git query runs.
        """

        root = discover_repository_root(start)
        return cls(root, runner=runner)

    @classmethod
    def from_root(
        cls, root: Path | str, *, runner: GitRunner | None = None
    ) -> "GitRepository":
        """Build a repository for an already-resolved ``root``."""

        return cls(Path(root), runner=runner)

    # --- root / validity --------------------------------------------------

    def get_root(self) -> Path:
        """Return the canonical repository root (7.2)."""

        return self._root

    def ensure_valid(self) -> None:
        """Verify the context is a usable, non-bare repository (R2).

        Raises :class:`GitRepositoryInvalidError` when Git cannot confirm a
        working tree at the bound root.
        """

        inside = self._runner.run("rev-parse", "--is-inside-work-tree")
        if not inside.ok or inside.stdout.strip() != "true":
            raise GitRepositoryInvalidError(
                f"'{self._root}' is not a usable Git working tree"
            )

    # --- refs / branches --------------------------------------------------

    def resolve_ref(self, name: str) -> str | None:
        """Resolve ``name`` to a full commit id, or ``None`` when it does not exist.

        Uses ``rev-parse --verify`` against the resolved object, which is
        read-only and never contacts a remote (R14).
        """

        output = self._runner.run("rev-parse", "--verify", "--quiet", f"{name}^{{commit}}")
        if not output.ok:
            return None
        commit = output.stdout.strip()
        return commit or None

    def branch_exists(self, name: str) -> bool:
        """Return whether a *local* branch ``name`` exists (R4)."""

        output = self._runner.run(
            "show-ref", "--verify", "--quiet", f"refs/heads/{name}"
        )
        return output.ok

    def get_branch(self, name: str) -> BranchRef | None:
        """Return the :class:`BranchRef` for a local branch, or ``None`` (R4)."""

        output = self._runner.run(
            "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"
        )
        if not output.ok:
            return None
        commit = output.stdout.strip()
        if not commit:
            return None
        return BranchRef(name=name, commit=commit)

    def resolve_base_branch(self, name: str) -> BranchRef:
        """Resolve ``project.base_branch`` as a usable local ref (R3).

        E2 never performs an implicit ``fetch``; a missing base branch raises
        :class:`BaseBranchNotFoundError` so the caller can surface it (INV-14).
        """

        branch = self.get_branch(name)
        if branch is None:
            raise BaseBranchNotFoundError(
                f"base branch '{name}' does not exist locally "
                "(ramalio does not fetch implicitly in E2)"
            )
        return branch

    # --- worktrees --------------------------------------------------------

    def list_worktrees(self) -> tuple[WorktreeInfo, ...]:
        """List registered worktrees from ``git worktree list --porcelain`` (R5).

        Parses the stable machine-readable format only; human-oriented output is
        never parsed (7.3).
        """

        output = self._runner.run("worktree", "list", "--porcelain", check=True)
        return _parse_worktree_porcelain(output.stdout)

    def get_worktree_by_path(self, path: Path | str) -> WorktreeInfo | None:
        """Return the worktree registered at ``path``, or ``None`` (7.2).

        ``path`` is normalized to a canonical absolute path before comparison so
        equivalent spellings match reliably (INV-05).
        """

        target = Path(path)
        target = target if target.is_absolute() else (self._root / target)
        target = _canonical(target)
        for worktree in self.list_worktrees():
            if worktree.path == target:
                return worktree
        return None

    def get_worktree_by_branch(self, branch: str) -> WorktreeInfo | None:
        """Return the worktree that currently has ``branch`` checked out (R4, R11)."""

        for worktree in self.list_worktrees():
            if worktree.branch == branch:
                return worktree
        return None

    def branch_checked_out_elsewhere(self, branch: str) -> WorktreeInfo | None:
        """Return the worktree using ``branch`` when one exists (R11).

        A thin, intention-revealing alias over :meth:`get_worktree_by_branch`
        used by lifecycle precondition checks (7.6).
        """

        return self.get_worktree_by_branch(branch)

    # --- status -----------------------------------------------------------

    def get_status(self, path: Path | str | None = None) -> GitStatus:
        """Return the minimal safety status for a checkout/worktree (R8).

        ``path`` selects the worktree to inspect; ``None`` uses the repository
        root.  Parses ``git status --porcelain=v1 --branch`` only (7.4).
        """

        target = self._root if path is None else Path(path)
        if not target.is_absolute():
            target = self._root / target
        output = self._runner.run(
            "status", "--porcelain=v1", "--branch", "--untracked-files=normal",
            check=True,
            cwd=target,
        )
        return _parse_status_porcelain(output.stdout)


# --- parsing helpers ------------------------------------------------------


def _canonical(path: Path) -> Path:
    """Return a canonical absolute path suitable for reliable comparison (INV-05).

    ``os.path.realpath`` semantics via ``Path.resolve`` collapse ``..`` and
    symlinks so two spellings of the same worktree compare equal.
    """

    try:
        return path.resolve()
    except OSError:  # pragma: no cover - defensive, resolve rarely raises
        return path.absolute()


def _parse_worktree_porcelain(text: str) -> tuple[WorktreeInfo, ...]:
    """Parse ``git worktree list --porcelain`` output into models (R5).

    Records are separated by blank lines.  Recognized attributes: ``worktree``,
    ``HEAD``, ``branch``, ``bare``, ``detached``, ``locked``, ``prunable``.
    Unknown lines are ignored so future Git additions do not break parsing.
    """

    worktrees: list[WorktreeInfo] = []
    current: dict[str, object] = {}

    def flush() -> None:
        if not current:
            return
        raw_path = current.get("path")
        if raw_path is None:
            current.clear()
            return
        branch_ref = current.get("branch")
        branch_name = _short_branch(branch_ref) if isinstance(branch_ref, str) else None
        worktrees.append(
            WorktreeInfo(
                path=_canonical(Path(str(raw_path))),
                head=current.get("head"),  # type: ignore[arg-type]
                branch=branch_name,
                bare=bool(current.get("bare", False)),
                detached=bool(current.get("detached", False)),
                locked=bool(current.get("locked", False)),
                prunable=bool(current.get("prunable", False)),
            )
        )
        current.clear()

    for line in text.splitlines():
        if line.strip() == "":
            flush()
            continue
        if line.startswith("worktree "):
            # A new record starts; flush any in-progress one defensively.
            flush()
            current["path"] = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD ") :].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :].strip()
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True
        elif line == "locked" or line.startswith("locked "):
            current["locked"] = True
        elif line == "prunable" or line.startswith("prunable "):
            current["prunable"] = True

    flush()
    return tuple(worktrees)


def _short_branch(ref: str) -> str:
    """Convert a ``refs/heads/<name>`` ref into the short branch name."""

    prefix = "refs/heads/"
    return ref[len(prefix) :] if ref.startswith(prefix) else ref


def _parse_status_porcelain(text: str) -> GitStatus:
    """Parse ``git status --porcelain=v1 --branch`` into a :class:`GitStatus` (R8).

    The first ``## `` line carries branch info; ``## HEAD (no branch)`` signals a
    detached HEAD.  Entries prefixed with ``??`` are untracked; any other entry
    is a tracked modification (dirty).
    """

    dirty = False
    untracked = False
    detached = False

    for line in text.splitlines():
        if line.startswith("## "):
            header = line[len("## ") :]
            if header.startswith("HEAD (no branch)"):
                detached = True
            continue
        if line == "":
            continue
        if line.startswith("??"):
            untracked = True
        else:
            dirty = True

    return GitStatus(dirty=dirty, untracked=untracked, detached=detached)
