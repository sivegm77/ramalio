"""Deterministic naming derivation from a canonical target (E1-S2).

Given a validated :class:`~ramalio.core.target.Target` and the project's
branch/worktree configuration, this module derives:

* the branch name, from ``[branch].pattern`` (R11);
* the worktree path, from ``[worktree].directory`` + ``[worktree].pattern`` (R12).

Derivation is pure: identical configuration and target always yield identical
names (INV-06).  This spec never creates branches, directories or worktrees
(INV-07, R16): it computes and validates names so E2 can act on already-resolved,
structurally-safe identities.

The only supported placeholder in E1 is ``{target}`` (7.4, R11/R12).  Speculative
placeholders (``{user}``, ``{port}``, ``{date}``, ...) are intentionally absent
until a spec justifies them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from .errors import (
    BranchPatternInvalidError,
    DerivedBranchInvalidError,
    DerivedWorktreePathInvalidError,
    WorktreePatternInvalidError,
)
from .target import Target

# The single supported placeholder token in E1 (7.4).
_TARGET_PLACEHOLDER: Final[str] = "{target}"

# Matches any ``{...}`` placeholder so unknown tokens can be rejected (R13).
_PLACEHOLDER_RE: Final[re.Pattern[str]] = re.compile(r"\{([^{}]*)\}")


@dataclass(frozen=True, slots=True)
class BranchRules:
    """Effective branch derivation rules (mirror of ``[branch]``).

    Lives in the core so naming stays independent of the configuration source;
    the config layer builds it.
    """

    pattern: str


@dataclass(frozen=True, slots=True)
class WorktreeRules:
    """Effective worktree derivation rules (mirror of ``[worktree]``)."""

    directory: str
    pattern: str


@dataclass(frozen=True, slots=True)
class ResolvedWorkspaceIdentity:
    """The resolved, structurally-safe identity for a target (7.8).

    Aggregates the canonical target with its derived branch name and worktree
    path.  Holding no persistent state, it is safe to build before E2 executes
    any Git/filesystem operation (INV-07).
    """

    target: Target
    branch_name: str
    worktree_path: PurePosixPath


def _validate_pattern(
    pattern: str,
    *,
    kind: str,
    error: type[BranchPatternInvalidError] | type[WorktreePatternInvalidError],
) -> None:
    """Reject empty patterns, unknown placeholders or a missing ``{target}`` (R13).

    ``kind`` is only used for diagnostics ("branch" / "worktree").
    """

    if pattern == "":
        raise error(f"{kind}.pattern must not be empty")

    unknown = sorted(
        {name for name in _PLACEHOLDER_RE.findall(pattern) if name != "target"}
    )
    if unknown:
        joined = ", ".join(f"{{{name}}}" for name in unknown)
        raise error(
            f"{kind}.pattern uses unsupported placeholder(s): {joined}. "
            f"Only {_TARGET_PLACEHOLDER} is supported in E1."
        )

    if _TARGET_PLACEHOLDER not in pattern:
        raise error(
            f"{kind}.pattern must contain the {_TARGET_PLACEHOLDER} placeholder"
        )


def _expand(pattern: str, target: Target) -> str:
    """Expand the ``{target}`` placeholder deterministically (INV-06)."""

    return pattern.replace(_TARGET_PLACEHOLDER, target.value)


# --- Git ref name validation (R14) ---------------------------------------
# Equivalent, centralized rules matching git-check-ref-format's fundamental
# constraints.  We validate read-only; we never shell out and never create the
# ref (R14, 7.6).  Keeping this in-process avoids shell injection entirely.

_REF_FORBIDDEN_SUBSTRINGS: Final[tuple[str, ...]] = ("..", "@{", "//")
# ASCII control chars, space, and the characters git forbids in ref names.
_REF_FORBIDDEN_CHARS: Final[frozenset[str]] = frozenset(
    {" ", "~", "^", ":", "?", "*", "[", "\\", "\x7f"}
)


def validate_branch_ref(name: str) -> None:
    """Validate ``name`` against fundamental Git ref-name rules (R14).

    Raises :class:`DerivedBranchInvalidError` when the name would be rejected by
    Git.  This never creates the branch.
    """

    def reject(reason: str) -> DerivedBranchInvalidError:
        return DerivedBranchInvalidError(
            f'Nombre de branch derivado inválido: "{name}". {reason}'
        )

    if name == "":
        raise reject("El nombre está vacío.")

    if any(ord(ch) < 0x20 for ch in name):
        raise reject("Contiene caracteres de control.")

    for ch in name:
        if ch in _REF_FORBIDDEN_CHARS:
            raise reject(f"Contiene un carácter no permitido: {ch!r}.")

    for bad in _REF_FORBIDDEN_SUBSTRINGS:
        if bad in name:
            raise reject(f"Contiene la secuencia prohibida {bad!r}.")

    if name.startswith("/") or name.endswith("/"):
        raise reject("No puede empezar ni terminar con '/'.")

    if name.endswith(".") or name.endswith(".lock"):
        raise reject("No puede terminar con '.' ni con '.lock'.")

    # A path component may not start with a dot nor end with '.lock'.
    for component in name.split("/"):
        if component == "":
            raise reject("Contiene un componente vacío.")
        if component.startswith("."):
            raise reject("Un componente no puede empezar con '.'.")
        if component.endswith(".lock"):
            raise reject("Un componente no puede terminar con '.lock'.")


def derive_branch(target: Target, rules: BranchRules) -> str:
    """Derive and validate the branch name for ``target`` (R11, R14).

    Raises
    ------
    BranchPatternInvalidError
        If the configured pattern is empty, misses ``{target}`` or uses an
        unknown placeholder (R13).
    DerivedBranchInvalidError
        If the expanded name is not a valid Git ref (R14).
    """

    _validate_pattern(rules.pattern, kind="branch", error=BranchPatternInvalidError)
    name = _expand(rules.pattern, target)
    validate_branch_ref(name)
    return name


def derive_worktree_path(target: Target, rules: WorktreeRules) -> PurePosixPath:
    """Derive and validate the worktree path relative to the repo root (R12, R15).

    The returned path is *relative* to the repository root discovered in E1-S0
    (7.5): ``<directory>/<expanded pattern>``.  E1-S2 does not resolve it against
    the real filesystem nor create it (INV-07); it enforces lexical/canonical
    safety only (7.7).

    Raises
    ------
    WorktreePatternInvalidError
        If the pattern is empty, misses ``{target}`` or uses an unknown
        placeholder (R13).
    DerivedWorktreePathInvalidError
        If the derived path is empty, escapes the boundary via ``..``, is
        absolute, or resolves to the repository root (R15).
    """

    _validate_pattern(
        rules.pattern, kind="worktree", error=WorktreePatternInvalidError
    )
    expanded = _expand(rules.pattern, target)

    directory = rules.directory
    if directory == "":
        raise DerivedWorktreePathInvalidError(
            "worktree.directory no puede estar vacío."
        )

    # Both fragments are interpreted relative to the repository root (7.5). An
    # absolute directory/pattern would break the boundary contract for E1.
    if directory.startswith("/") or expanded.startswith("/"):
        raise DerivedWorktreePathInvalidError(
            "El path de worktree debe ser relativo al root del repositorio."
        )

    relative = PurePosixPath(directory) / expanded

    def reject(reason: str) -> DerivedWorktreePathInvalidError:
        return DerivedWorktreePathInvalidError(
            f'Path de worktree derivado inválido: "{relative}". {reason}'
        )

    # Lexical boundary check (7.7): no component may escape via '..'. We reject
    # traversal outright rather than resolving against the filesystem, so
    # symlinks can never be used to authorize an escape (R15).
    parts = [part for part in relative.parts if part != "."]
    if any(part == ".." for part in parts):
        raise reject("Contiene '..' que escaparía del boundary permitido.")

    if not parts:
        raise reject("El path resultante está vacío.")

    # A pattern that resolves to the repository root itself (e.g. the directory
    # only, with an empty expansion) would target the primary checkout (R15).
    expanded_parts = [
        part for part in PurePosixPath(expanded).parts if part not in (".", "")
    ]
    if not expanded_parts:
        raise reject("El patrón resuelve al root del checkout principal.")

    return relative


class WorkspaceNaming:
    """Naming service that derives branch and worktree names for a project.

    A single instance carries the resolved branch/worktree rules and derives an
    aggregated :class:`ResolvedWorkspaceIdentity` for any validated target,
    without mutating Git or the filesystem (INV-07, R16).
    """

    def __init__(self, branch: BranchRules, worktree: WorktreeRules) -> None:
        self._branch = branch
        self._worktree = worktree

    def derive_branch(self, target: Target) -> str:
        return derive_branch(target, self._branch)

    def derive_worktree_path(self, target: Target) -> PurePosixPath:
        return derive_worktree_path(target, self._worktree)

    def resolve(self, target: Target) -> ResolvedWorkspaceIdentity:
        """Derive the full, structurally-safe identity for ``target`` (7.8)."""

        return ResolvedWorkspaceIdentity(
            target=target,
            branch_name=self.derive_branch(target),
            worktree_path=self.derive_worktree_path(target),
        )
