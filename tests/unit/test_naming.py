"""Unit tests for naming derivation (E1-S2).

Covers CT-10..CT-17 and AC-08..AC-13.  Derivation is pure and creates no
branches, directories or worktrees (INV-07, R16, AC-13).
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest

from ramalio.core.errors import (
    BranchPatternInvalidError,
    DerivedBranchInvalidError,
    DerivedWorktreePathInvalidError,
    WorktreePatternInvalidError,
)
from ramalio.core.naming import (
    BranchRules,
    WorkspaceNaming,
    WorktreeRules,
    derive_branch,
    derive_worktree_path,
    validate_branch_ref,
)
from ramalio.core.target import Target

SPEC_TARGET = Target.from_trusted("E7-S8-convergencia-schema-tests")
FEATURE_TARGET = Target.from_trusted("FEATURE-123-login")
TASK_TARGET = Target.from_trusted("TASK-15-retries")


# --- CT-10 branch valid / AC-08 -------------------------------------------


def test_branch_pattern_derives_deterministically() -> None:
    rules = BranchRules(pattern="spec/{target}")
    first = derive_branch(SPEC_TARGET, rules)
    second = derive_branch(SPEC_TARGET, rules)
    assert first == "spec/E7-S8-convergencia-schema-tests"
    assert first == second  # determinism (INV-06)


# --- CT-11 empty branch pattern -------------------------------------------


def test_empty_branch_pattern_is_rejected() -> None:
    with pytest.raises(BranchPatternInvalidError) as excinfo:
        derive_branch(FEATURE_TARGET, BranchRules(pattern=""))
    assert excinfo.value.code == "BRANCH_PATTERN_INVALID"


def test_branch_pattern_without_target_is_rejected() -> None:
    with pytest.raises(BranchPatternInvalidError):
        derive_branch(FEATURE_TARGET, BranchRules(pattern="spec/fixed"))


# --- CT-12 unknown placeholder / AC-09 ------------------------------------


def test_unknown_placeholder_in_branch_is_rejected() -> None:
    with pytest.raises(BranchPatternInvalidError) as excinfo:
        derive_branch(FEATURE_TARGET, BranchRules(pattern="spec/{target}/{user}"))
    assert excinfo.value.code == "BRANCH_PATTERN_INVALID"


def test_unknown_placeholder_in_worktree_is_rejected() -> None:
    with pytest.raises(WorktreePatternInvalidError) as excinfo:
        derive_worktree_path(
            FEATURE_TARGET,
            WorktreeRules(directory=".local-wt", pattern="{date}-{target}"),
        )
    assert excinfo.value.code == "WORKTREE_PATTERN_INVALID"


# --- CT-13 invalid branch ref / AC-10 -------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "spec/..",  # traversal-like ref sequence
        "spec/target~1",  # tilde
        "spec/target:name",  # colon
        "spec/target name",  # space
        "spec/target.lock",  # ends with .lock
        "spec//target",  # empty component
        "/spec/target",  # leading slash
    ],
)
def test_invalid_ref_shapes_are_rejected(bad: str) -> None:
    with pytest.raises(DerivedBranchInvalidError) as excinfo:
        validate_branch_ref(bad)
    assert excinfo.value.code == "DERIVED_BRANCH_INVALID"


def test_derived_branch_ref_matches_git_check_ref_format() -> None:
    # Cross-check our read-only rules against real Git without mutating it.
    if _git_available():
        for good in ["spec/FEATURE-123-login", "task/TASK-15-retries"]:
            assert _git_ref_ok(good) is True
            validate_branch_ref(good)  # our validator agrees
        for bad in ["spec/target name", "spec/..", "spec/target.lock"]:
            assert _git_ref_ok(bad) is False
            with pytest.raises(DerivedBranchInvalidError):
                validate_branch_ref(bad)


# --- CT-14 worktree path valid --------------------------------------------


def test_worktree_path_within_directory() -> None:
    path = derive_worktree_path(
        FEATURE_TARGET, WorktreeRules(directory=".local-wt", pattern="{target}")
    )
    assert path == PurePosixPath(".local-wt/FEATURE-123-login")


def test_worktree_path_is_deterministic() -> None:
    rules = WorktreeRules(directory=".worktrees", pattern="wt-{target}")
    assert derive_worktree_path(TASK_TARGET, rules) == derive_worktree_path(
        TASK_TARGET, rules
    )


# --- CT-15 path traversal / AC-11 -----------------------------------------


def test_path_traversal_is_rejected() -> None:
    with pytest.raises(DerivedWorktreePathInvalidError) as excinfo:
        derive_worktree_path(
            FEATURE_TARGET,
            WorktreeRules(directory="../outside", pattern="{target}"),
        )
    assert excinfo.value.code == "DERIVED_WORKTREE_PATH_INVALID"


def test_absolute_directory_is_rejected() -> None:
    with pytest.raises(DerivedWorktreePathInvalidError):
        derive_worktree_path(
            FEATURE_TARGET,
            WorktreeRules(directory="/etc", pattern="{target}"),
        )


# --- CT-16 path to root ---------------------------------------------------


def test_pattern_resolving_to_root_is_rejected() -> None:
    # A pattern that expands to "." would target the primary checkout root.
    # With {target} mandatory this is caught at pattern-validation time, so the
    # root can never be derived as a worktree path (R13/R15).
    with pytest.raises(WorktreePatternInvalidError):
        derive_worktree_path(
            FEATURE_TARGET,
            WorktreeRules(directory=".", pattern="."),
        )


def test_directory_dot_with_target_stays_inside_repo() -> None:
    # directory="." is legal as long as {target} keeps the path below the root.
    path = derive_worktree_path(
        FEATURE_TARGET, WorktreeRules(directory=".", pattern="{target}")
    )
    assert path == PurePosixPath("FEATURE-123-login")


# --- CT-17 no mutations / AC-13 -------------------------------------------


def test_derivation_creates_no_branch_or_directory(git_repo: Path) -> None:
    before_dirs = sorted(p.name for p in git_repo.iterdir())
    before_refs = _git_refs(git_repo)

    naming = WorkspaceNaming(
        branch=BranchRules(pattern="spec/{target}"),
        worktree=WorktreeRules(directory=".local-wt", pattern="{target}"),
    )
    identity = naming.resolve(FEATURE_TARGET)

    assert identity.branch_name == "spec/FEATURE-123-login"
    assert identity.worktree_path == PurePosixPath(".local-wt/FEATURE-123-login")
    # No worktree directory nor ref was created (INV-07, R16).
    assert not (git_repo / ".local-wt").exists()
    assert sorted(p.name for p in git_repo.iterdir()) == before_dirs
    assert _git_refs(git_repo) == before_refs


# --- AC-12 three conventions with the same service ------------------------


def test_same_naming_service_serves_three_conventions() -> None:
    naming = WorkspaceNaming(
        branch=BranchRules(pattern="spec/{target}"),
        worktree=WorktreeRules(directory=".local-wt", pattern="{target}"),
    )
    for target in (SPEC_TARGET, FEATURE_TARGET, TASK_TARGET):
        identity = naming.resolve(target)
        assert identity.branch_name == f"spec/{target.value}"
        assert identity.worktree_path == PurePosixPath(f".local-wt/{target.value}")


# --- helpers --------------------------------------------------------------


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"], check=True, capture_output=True, text=True
        )
        return True
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return False


def _git_ref_ok(name: str) -> bool:
    result = subprocess.run(
        ["git", "check-ref-format", f"refs/heads/{name}"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _git_refs(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname)"],
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in result.stdout.splitlines() if line)
