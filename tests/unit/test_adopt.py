"""End-to-end and unit tests for `ramalio adopt` (E2-S2).

Covers CT-01..CT-10 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories.  The service is exercised directly (unit) and through the CLI
wrapper (integration) to prove the public contract.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.adopt import (
    AdoptionScenario,
    AdoptWorkspaceService,
)
from ramalio.core.errors import (
    AdoptBranchInOtherWorktreeError,
    AdoptBranchNotFoundError,
    AdoptPostconditionFailedError,
    AdoptWorktreeBranchMismatchError,
    AdoptWorktreeDetachedError,
    AdoptWorktreePathConflictError,
)
from ramalio.core.result import ExitCode
from ramalio.git.repository import GitRepository

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


def _service(project_root: Path) -> AdoptWorkspaceService:
    config = resolve_project_config(project_root)
    return AdoptWorkspaceService(config)


def _wt_path(project_root: Path, target: str) -> Path:
    return (project_root / ".local-wt" / target).resolve()


# --- CT-01: existing compatible clean --------------------------------------


def test_ct01_existing_compatible_clean_adopts_without_mutation(
    project: Path, run_git
) -> None:
    wt = _wt_path(project, "feature-one")
    run_git(project, "worktree", "add", "-b", "feature-one", str(wt))

    before = _snapshot(project)
    outcome = _service(project).run("feature-one")

    # AC-01: no mutations to branches/worktrees.
    assert _snapshot(project) == before
    assert outcome.adoption_mode == "existing-worktree"
    assert outcome.target == "feature-one"
    assert outcome.branch == "feature-one"
    assert outcome.worktree_path == wt
    assert outcome.git_dirty is False


# --- CT-02: existing compatible dirty --------------------------------------


def test_ct02_existing_compatible_dirty_reports_dirty(project: Path, run_git) -> None:
    wt = _wt_path(project, "feature-two")
    run_git(project, "worktree", "add", "-b", "feature-two", str(wt))
    (wt / "dirty.txt").write_text("uncommitted\n", encoding="utf-8")

    outcome = _service(project).run("feature-two")

    # AC-08 / R9: dirty compatible worktree adopts and reports git_dirty=true.
    assert outcome.adoption_mode == "existing-worktree"
    assert outcome.git_dirty is True


# --- CT-03: branch only -> create worktree ---------------------------------


def test_ct03_branch_only_creates_worktree(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-three", "main")

    outcome = _service(project).run("feature-three")

    repo = GitRepository.from_root(project)
    wt = _wt_path(project, "feature-three")
    registered = repo.get_worktree_by_path(wt)
    assert registered is not None
    assert registered.branch == "feature-three"

    # AC-02: only the worktree was created; branch was preexisting.
    assert outcome.adoption_mode == "created-worktree"
    assert outcome.worktree_path == wt
    assert outcome.branch == "feature-three"


def test_ct03_branch_only_does_not_create_new_branch(project: Path, run_git) -> None:
    # The preexisting branch's commit must be unchanged (no new branch, R3/R10).
    run_git(project, "branch", "feature-3b", "main")
    repo = GitRepository.from_root(project)
    commit_before = repo.get_branch("feature-3b").commit

    _service(project).run("feature-3b")

    assert repo.get_branch("feature-3b").commit == commit_before


# --- CT-04: branch missing -> fail -----------------------------------------


def test_ct04_branch_missing_fails_without_creating(project: Path) -> None:
    before = _snapshot(project)
    with pytest.raises(AdoptBranchNotFoundError) as exc:
        _service(project).run("feature-four")
    assert "init" in str(exc.value)  # R4 guidance

    # AC-03: nothing created.
    assert _snapshot(project) == before
    assert not GitRepository.from_root(project).branch_exists("feature-four")


# --- CT-05: branch checked out at another path -> fail ---------------------


def test_ct05_branch_in_other_worktree_fails(project: Path, run_git) -> None:
    other = (project / ".local-wt" / "elsewhere").resolve()
    run_git(project, "worktree", "add", "-b", "feature-five", str(other))

    before = _snapshot(project)
    with pytest.raises(AdoptBranchInOtherWorktreeError):
        _service(project).run("feature-five")

    # AC-04: the other worktree is not moved or deleted.
    assert _snapshot(project) == before


# --- CT-06: canonical path is an ordinary directory -> fail ----------------


def test_ct06_path_conflict_ordinary_directory_fails(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-six", "main")
    wt = _wt_path(project, "feature-six")
    wt.mkdir(parents=True)
    (wt / "keep.txt").write_text("keep\n", encoding="utf-8")

    before = _snapshot(project)
    with pytest.raises(AdoptWorktreePathConflictError):
        _service(project).run("feature-six")

    # AC-05: the occupied path is not deleted or modified.
    assert _snapshot(project) == before
    assert (wt / "keep.txt").read_text(encoding="utf-8") == "keep\n"


# --- CT-07: canonical path uses another branch -> fail ---------------------


def test_ct07_path_uses_other_branch_fails(project: Path, run_git) -> None:
    wt = _wt_path(project, "feature-seven")
    # Register the canonical path but with a DIFFERENT branch checked out.
    run_git(project, "worktree", "add", "-b", "other-branch", str(wt))
    # Also create the derived branch so BRANCH_MISSING does not preempt.
    run_git(project, "branch", "feature-seven", "main")

    before = _snapshot(project)
    with pytest.raises(AdoptWorktreeBranchMismatchError):
        _service(project).run("feature-seven")

    # AC-06: nothing mutated.
    assert _snapshot(project) == before


# --- CT-08: detached worktree at canonical path -> fail --------------------


def test_ct08_detached_worktree_fails(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-eight", "main")
    wt = _wt_path(project, "feature-eight")
    head = run_git(project, "rev-parse", "HEAD").strip()
    # Attach a worktree at the canonical path in detached HEAD state.
    run_git(project, "worktree", "add", "--detach", str(wt), head)

    with pytest.raises(AdoptWorktreeDetachedError):
        _service(project).run("feature-eight")


# --- CT-09: postcondition failure after worktree creation -> rollback ------


class _BadHeadRepo(GitRepository):
    """Repository whose observed worktree reports no HEAD, failing postcondition."""

    def get_worktree_by_path(self, path):
        info = super().get_worktree_by_path(path)
        if info is None:
            return None
        from dataclasses import replace

        return replace(info, head=None)


def test_ct09_postcondition_failure_rolls_back_worktree_keeps_branch(
    project: Path, run_git
) -> None:
    run_git(project, "branch", "feature-nine", "main")
    config = resolve_project_config(project)
    bad_repo = _BadHeadRepo.from_root(project)
    service = AdoptWorkspaceService(config, repository=bad_repo)

    with pytest.raises(AdoptPostconditionFailedError):
        service.run("feature-nine")

    verify_repo = GitRepository.from_root(project)
    # AC-10 / R13 / R15: the created worktree is retired, the branch is kept.
    assert verify_repo.get_worktree_by_path(_wt_path(project, "feature-nine")) is None
    assert verify_repo.branch_exists("feature-nine")


# --- CT-10: repeated adopt is idempotent -----------------------------------


def test_ct10_repeated_adopt_does_not_duplicate(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-ten", "main")

    first = _service(project).run("feature-ten")
    assert first.adoption_mode == "created-worktree"

    repo = GitRepository.from_root(project)
    worktrees_after_first = repo.list_worktrees()

    # AC-09 / R14: a second adopt on a now-compatible workspace succeeds without
    # creating a second worktree.
    second = _service(project).run("feature-ten")
    assert second.adoption_mode == "existing-worktree"
    assert repo.list_worktrees() == worktrees_after_first


# --- classification unit checks (T2/T10) -----------------------------------


def test_classify_branch_only(project: Path, run_git) -> None:
    run_git(project, "branch", "cls-branch-only", "main")
    service = _service(project)
    identity = service._resolve_identity("cls-branch-only")
    obs = service._observer.observe(identity)
    assert service._classify(identity, obs) is AdoptionScenario.BRANCH_ONLY


def test_classify_branch_missing(project: Path) -> None:
    service = _service(project)
    identity = service._resolve_identity("cls-missing")
    obs = service._observer.observe(identity)
    assert service._classify(identity, obs) is AdoptionScenario.BRANCH_MISSING


# --- no network side effects -----------------------------------------------


def test_adopt_issues_no_network_commands(project: Path, run_git) -> None:
    from ramalio.git.lifecycle import GitWriter
    from ramalio.git.runner import GitRunner

    class _SpyRunner(GitRunner):
        def __init__(self, cwd) -> None:
            super().__init__(cwd)
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args, check=False, cwd=None):
            self.calls.append(tuple(args))
            return super().run(*args, check=check, cwd=cwd)

    run_git(project, "branch", "feature-net", "main")
    config = resolve_project_config(project)
    repo_spy = _SpyRunner(project)
    writer_spy = _SpyRunner(project)
    repo = GitRepository.from_root(project, runner=repo_spy)
    writer = GitWriter(project, runner=writer_spy)
    service = AdoptWorkspaceService(config, repository=repo, writer=writer)

    service.run("feature-net")

    forbidden = frozenset({"fetch", "pull", "push", "remote", "clone"})
    all_calls = repo_spy.calls + writer_spy.calls
    assert all_calls
    for argv in all_calls:
        assert argv and argv[0] not in forbidden, f"network command issued: {argv}"


# --- CLI integration -------------------------------------------------------


def test_cli_adopt_branch_only_prints_structured_result(
    project: Path, monkeypatch, run_git
) -> None:
    run_git(project, "branch", "feature-cli", "main")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["adopt", "feature-cli"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "target: feature-cli" in out
    assert "adoption_mode: created-worktree" in out
    assert "git_dirty: false" in out
    assert stderr.getvalue() == ""

    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(_wt_path(project, "feature-cli")) is not None


def test_cli_adopt_branch_missing_maps_to_state_error(
    project: Path, monkeypatch
) -> None:
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["adopt", "feature-absent"], stdout=stdout, stderr=stderr)

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
    tree = (
        tuple(sorted(str(p) for p in local_wt.rglob("*"))) if local_wt.exists() else ()
    )
    return branches, worktrees, tree


def _git(root: Path, *args: str) -> str:
    import subprocess

    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout



# --- H1 (E7-S0): adopt runs under the common LifecycleTransaction ----------


def test_adopt_transaction_rolls_back_created_worktree_keeps_branch(
    project: Path, run_git
) -> None:
    """A failure after adopt attaches a worktree must compensate under the
    common LifecycleTransaction: the worktree adopt created disappears, while
    the preexisting branch is preserved (E7-S0 R10/R15)."""

    run_git(project, "branch", "feature-tx", "main")
    config = resolve_project_config(project)
    # _BadHeadRepo makes the postcondition verification fail *after* the
    # worktree has been created, exercising the transaction rollback path.
    bad_repo = _BadHeadRepo.from_root(project)
    service = AdoptWorkspaceService(config, repository=bad_repo)

    with pytest.raises(AdoptPostconditionFailedError):
        service.run("feature-tx")

    verify_repo = GitRepository.from_root(project)
    assert verify_repo.get_worktree_by_path(_wt_path(project, "feature-tx")) is None
    # The preexisting branch must never be part of adopt's rollback.
    assert verify_repo.branch_exists("feature-tx")


def test_adopt_partial_rollback_is_diagnosable(project: Path, run_git) -> None:
    """When compensation cannot fully retire the worktree adopt created, adopt
    surfaces AdoptRollbackIncompleteError (ROLLBACK_PARTIAL) in addition to the
    primary cause, so the partial state stays diagnosable (E7-S0 R6/R16)."""

    from ramalio.core.errors import (
        AdoptRollbackIncompleteError,
        GitCommandError,
    )
    from ramalio.git.lifecycle import GitWriter

    run_git(project, "branch", "feature-partial", "main")
    config = resolve_project_config(project)

    class _FailingRemoveWriter(GitWriter):
        """Creates worktrees normally but fails to remove them (blocks rollback)."""

        def remove_worktree(self, worktree_path, *, force: bool = True) -> None:
            raise GitCommandError("simulated worktree removal failure")

    bad_repo = _BadHeadRepo.from_root(project)
    writer = _FailingRemoveWriter(project)
    service = AdoptWorkspaceService(config, repository=bad_repo, writer=writer)

    # Postcondition fails -> transaction rolls back -> compensation (remove)
    # fails -> ROLLBACK_PARTIAL surfaced as AdoptRollbackIncompleteError.
    with pytest.raises(AdoptRollbackIncompleteError) as exc:
        service.run("feature-partial")

    # The original cause code is preserved for diagnosis.
    assert exc.value.cause_code == "ADOPT_POSTCONDITION_FAILED"
    # The preexisting branch is still never deleted, even on partial rollback.
    assert GitRepository.from_root(project).branch_exists("feature-partial")
