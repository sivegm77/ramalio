"""End-to-end and unit tests for `ramalio init` (E2-S1).

Covers CT-01..CT-10 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories.  The service is exercised directly (unit) and through the CLI
wrapper (integration) to prove the public contract.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import default_handlers, main
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    BranchAlreadyExistsError,
    GitCommandError,
    InitGitOperationFailedError,
    InitPostconditionFailedError,
    InitRollbackIncompleteError,
    WorkspaceAlreadyExistsError,
    WorktreeAlreadyRegisteredError,
    WorktreePathAlreadyExistsError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.result import ExitCode
from ramalio.git.lifecycle import GitWriter
from ramalio.git.repository import GitRepository
from ramalio.git.runner import GitRunner

_CONFIG_BODY = """
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "{target}"
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    """A real repository with a commit on main and a simple-git config."""

    write_config(git_repo_with_commit, _CONFIG_BODY)
    return git_repo_with_commit


def _service(project_root: Path) -> InitWorkspaceService:
    config = resolve_project_config(project_root)
    return InitWorkspaceService(config)


# --- CT-01: happy path -----------------------------------------------------


def test_ct01_happy_path_creates_branch_and_worktree(project: Path) -> None:
    outcome = _service(project).run("feature-one")

    repo = GitRepository.from_root(project)
    assert repo.branch_exists("feature-one")
    wt_path = project / ".local-wt" / "feature-one"
    registered = repo.get_worktree_by_path(wt_path)
    assert registered is not None
    assert registered.branch == "feature-one"

    # AC-08: result exposes target, branch and path.
    assert outcome.target == "feature-one"
    assert outcome.branch == "feature-one"
    assert outcome.worktree_path == wt_path.resolve()
    assert outcome.base_branch == "main"


# --- CT-02: invoking HEAD differs from base --------------------------------


def test_ct02_branch_born_from_base_even_if_head_differs(
    project: Path, run_git
) -> None:
    # Move the primary checkout to a divergent branch/commit.
    run_git(project, "checkout", "-q", "-b", "divergent")
    (project / "extra.txt").write_text("x\n", encoding="utf-8")
    run_git(project, "add", "extra.txt")
    run_git(project, "commit", "-q", "-m", "divergent tip")

    _service(project).run("feature-two")

    repo = GitRepository.from_root(project)
    main = repo.get_branch("main")
    feature = repo.get_branch("feature-two")
    assert feature is not None and main is not None
    # R6: branch started from base ref, not the divergent HEAD.
    assert feature.commit == main.commit

    # AC-02 / R8: the invoking checkout stays on its original branch.
    current = run_git(project, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert current == "divergent"


# --- CT-03: branch already exists ------------------------------------------


def test_ct03_existing_branch_blocks_without_mutation(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-three", "main")

    before = _snapshot(project)
    with pytest.raises(BranchAlreadyExistsError) as exc:
        _service(project).run("feature-three")
    assert "adopt" in str(exc.value)  # R3 guidance

    # AC-03: no mutations.
    assert _snapshot(project) == before


# --- CT-04: path already exists --------------------------------------------


def test_ct04_existing_path_blocks_without_mutation(project: Path) -> None:
    wt_path = project / ".local-wt" / "feature-four"
    wt_path.mkdir(parents=True)
    (wt_path / "keep.txt").write_text("keep\n", encoding="utf-8")

    before = _snapshot(project)
    with pytest.raises(WorktreePathAlreadyExistsError):
        _service(project).run("feature-four")

    # AC-04: nothing removed/created; branch not created.
    assert _snapshot(project) == before
    assert not GitRepository.from_root(project).branch_exists("feature-four")


# --- CT-05: worktree already registered ------------------------------------


def test_ct05_registered_worktree_blocks(project: Path, run_git) -> None:
    wt_path = project / ".local-wt" / "feature-five"
    run_git(project, "worktree", "add", "-b", "other-branch", str(wt_path))

    with pytest.raises(WorktreeAlreadyRegisteredError):
        _service(project).run("feature-five")


# --- CT-06: second init idempotency ----------------------------------------


def test_ct06_second_init_does_not_duplicate(project: Path) -> None:
    _service(project).run("feature-six")

    repo = GitRepository.from_root(project)
    worktrees_before = repo.list_worktrees()

    with pytest.raises(WorkspaceAlreadyExistsError):
        _service(project).run("feature-six")

    # AC-05: no second workspace created.
    assert repo.list_worktrees() == worktrees_before


# --- CT-07: failure creating worktree -> rollback owned branch -------------


class _FailWorktreeWriter(GitWriter):
    """Writer that creates the branch but fails attaching the worktree (CT-07)."""

    def add_worktree_for_branch(self, *, branch: str, worktree_path: Path) -> None:
        raise GitCommandError("simulated worktree add failure", args=("worktree", "add"))


def test_ct07_worktree_failure_rolls_back_owned_branch(project: Path) -> None:
    config = resolve_project_config(project)
    writer = _FailWorktreeWriter(project)
    service = InitWorkspaceService(config, writer=writer)

    with pytest.raises(InitGitOperationFailedError):
        service.run("feature-seven")

    # R11: the branch created by this execution is retired on rollback.
    repo = GitRepository.from_root(project)
    assert not repo.branch_exists("feature-seven")
    assert repo.get_worktree_by_path(project / ".local-wt" / "feature-seven") is None


# --- CT-08: postcondition failure -> safe rollback -------------------------


class _BadHeadRepo(GitRepository):
    """Repository whose observed worktree reports no HEAD, failing postcondition."""

    def get_worktree_by_path(self, path):
        info = super().get_worktree_by_path(path)
        if info is None:
            return None
        # Force an incoherent postcondition: worktree present but headless.
        from dataclasses import replace

        return replace(info, head=None)


def test_ct08_postcondition_failure_triggers_safe_rollback(project: Path) -> None:
    config = resolve_project_config(project)
    bad_repo = _BadHeadRepo.from_root(project)
    service = InitWorkspaceService(config, repository=bad_repo)

    with pytest.raises(InitPostconditionFailedError):
        service.run("feature-eight")

    # Rollback used ownership and removed what this execution created.
    verify_repo = GitRepository.from_root(project)
    assert not verify_repo.branch_exists("feature-eight")
    assert verify_repo.get_worktree_by_path(
        project / ".local-wt" / "feature-eight"
    ) is None


# --- CT-09: preexisting branch is never deleted by rollback ----------------


def test_ct09_rollback_never_deletes_preexisting_branch(project: Path, run_git) -> None:
    # A preexisting branch that is NOT owned by this execution.
    run_git(project, "branch", "preexisting", "main")

    config = resolve_project_config(project)
    repo = GitRepository.from_root(project)
    service = InitWorkspaceService(config, repository=repo)

    # Compensating a branch this execution never created (owned-branch does not
    # exist) is a safe no-op and must never touch an unrelated preexisting
    # branch (R13, E7-S0).
    class _Id:
        branch_name = "owned-branch"
        target = type("T", (), {"value": "owned-branch"})()

    service._undo_branch(_Id())  # no-op, must not raise

    assert repo.branch_exists("preexisting")


def test_ct09_rollback_incomplete_when_owned_branch_still_in_use(
    project: Path, run_git
) -> None:
    # A branch this execution owns is still checked out in a worktree.  The
    # branch compensation must not force-break it and must report the rollback
    # as incomplete (R13, INV-006, E7-S0).
    used_path = project / ".local-wt" / "elsewhere"
    run_git(project, "worktree", "add", "-b", "owned-used", str(used_path))

    config = resolve_project_config(project)
    repo = GitRepository.from_root(project)
    service = InitWorkspaceService(config, repository=repo)

    # Build an identity whose derived branch is the one still checked out, so
    # _undo_branch sees it as in-use and refuses to delete it.
    class _Id:
        branch_name = "owned-used"
        target = type("T", (), {"value": "owned-used"})()

    with pytest.raises(InitRollbackIncompleteError):
        service._undo_branch(_Id())
    assert repo.branch_exists("owned-used")


# --- CT-10: no network side effects ----------------------------------------


class _SpyRunner(GitRunner):
    def __init__(self, cwd) -> None:
        super().__init__(cwd)
        self.calls: list[tuple[str, ...]] = []

    def run(self, *args, check=False, cwd=None):
        self.calls.append(tuple(args))
        return super().run(*args, check=check, cwd=cwd)


_FORBIDDEN = frozenset({"fetch", "pull", "push", "remote", "clone"})


def test_ct10_init_issues_no_network_commands(project: Path) -> None:
    config = resolve_project_config(project)
    repo_spy = _SpyRunner(project)
    writer_spy = _SpyRunner(project)
    repo = GitRepository.from_root(project, runner=repo_spy)
    writer = GitWriter(project, runner=writer_spy)
    service = InitWorkspaceService(config, repository=repo, writer=writer)

    service.run("feature-ten")

    all_calls = repo_spy.calls + writer_spy.calls
    assert all_calls
    for argv in all_calls:
        assert argv and argv[0] not in _FORBIDDEN, f"network command issued: {argv}"


# --- CLI integration -------------------------------------------------------


def test_cli_init_success_prints_structured_result(
    project: Path, monkeypatch
) -> None:
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["init", "feature-cli"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "target: feature-cli" in out
    assert "branch: feature-cli" in out
    assert "base_branch: main" in out
    assert stderr.getvalue() == ""

    repo = GitRepository.from_root(project)
    assert repo.branch_exists("feature-cli")


def test_cli_init_branch_exists_maps_to_state_error(
    project: Path, monkeypatch, run_git
) -> None:
    run_git(project, "branch", "feature-dup", "main")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["init", "feature-dup"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.STATE_ERROR
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("error: ")


# --- helpers ---------------------------------------------------------------


def _snapshot(root: Path) -> tuple:
    """A cheap snapshot of branches + worktree registry + local-wt tree."""

    repo = GitRepository.from_root(root)
    branches = tuple(
        sorted(
            line.strip().lstrip("* ").strip()
            for line in _git(root, "branch").splitlines()
            if line.strip()
        )
    )
    worktrees = tuple(sorted(str(w.path) for w in repo.list_worktrees()))
    local_wt = root / ".local-wt"
    tree = tuple(sorted(str(p) for p in local_wt.rglob("*"))) if local_wt.exists() else ()
    return branches, worktrees, tree


def _git(root: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
