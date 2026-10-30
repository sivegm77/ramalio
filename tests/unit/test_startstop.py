"""End-to-end and unit tests for `ramalio start` / `ramalio stop` (E3-S2).

Covers CT-01..CT-10 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories.  In a Git-only project start/stop are valid, idempotent no-ops
that preserve the workspace.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    WorkspaceInconsistentError,
    WorkspaceNotActiveError,
    WorkspaceNotFoundError,
)
from ramalio.core.result import ExitCode
from ramalio.core.startstop import (
    StartWorkspaceService,
    StopWorkspaceService,
)
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
    write_config(git_repo_with_commit, _CONFIG_BODY)
    return git_repo_with_commit


def _start(project_root: Path) -> StartWorkspaceService:
    return StartWorkspaceService(resolve_project_config(project_root))


def _stop(project_root: Path) -> StopWorkspaceService:
    return StopWorkspaceService(resolve_project_config(project_root))


def _wt(project_root: Path, target: str) -> Path:
    return (project_root / ".local-wt" / target).resolve()


def _add(run_git, project_root: Path, target: str) -> Path:
    wt = _wt(project_root, target)
    run_git(project_root, "worktree", "add", "-b", target, str(wt))
    return wt


def _snapshot(root: Path) -> tuple:
    repo = GitRepository.from_root(root)
    worktrees = tuple(sorted(str(w.path) for w in repo.list_worktrees()))
    local_wt = root / ".local-wt"
    tree = (
        tuple(sorted(str(p) for p in local_wt.rglob("*"))) if local_wt.exists() else ()
    )
    return worktrees, tree


# --- CT-01: stop READY -> no-op --------------------------------------------


def test_ct01_stop_ready_noop(project: Path, run_git) -> None:
    _add(run_git, project, "feature-one")
    before = _snapshot(project)

    outcome = _stop(project).run("feature-one")

    assert outcome.no_op is True
    assert outcome.resources_stopped == 0
    # AC-10: no mutations.
    assert _snapshot(project) == before


# --- CT-02: stop DIRTY preserves changes -----------------------------------


def test_ct02_stop_dirty_preserves(project: Path, run_git) -> None:
    wt = _add(run_git, project, "feature-two")
    (wt / "work.txt").write_text("in progress\n", encoding="utf-8")

    outcome = _stop(project).run("feature-two")

    assert outcome.no_op is True
    # AC-02: dirty change preserved.
    assert (wt / "work.txt").read_text(encoding="utf-8") == "in progress\n"


# --- CT-03: start READY -> no-op -------------------------------------------


def test_ct03_start_ready_noop(project: Path, run_git) -> None:
    _add(run_git, project, "feature-three")
    outcome = _start(project).run("feature-three")

    assert outcome.no_op is True
    assert outcome.resources_started == 0
    assert outcome.workspace_path == _wt(project, "feature-three")


# --- CT-04: missing -> fail ------------------------------------------------


def test_ct04_missing_fails(project: Path) -> None:
    with pytest.raises(WorkspaceNotFoundError):
        _start(project).run("feature-four")
    with pytest.raises(WorkspaceNotFoundError):
        _stop(project).run("feature-four")


# --- CT-05: branch-only -> not active, suggest adopt -----------------------


def test_ct05_branch_only_not_active(project: Path, run_git) -> None:
    run_git(project, "branch", "feature-five", "main")

    with pytest.raises(WorkspaceNotActiveError) as exc:
        _start(project).run("feature-five")
    assert "adopt" in str(exc.value)

    # AC-05: the worktree is not recreated.
    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(_wt(project, "feature-five")) is None


# --- CT-06: inconsistent -> fail closed ------------------------------------


def test_ct06_inconsistent_blocks(project: Path, run_git) -> None:
    other = (project / ".local-wt" / "elsewhere").resolve()
    run_git(project, "worktree", "add", "-b", "feature-six", str(other))

    with pytest.raises(WorkspaceInconsistentError):
        _stop(project).run("feature-six")


def test_ct06_detached_blocks(project: Path, run_git) -> None:
    wt = _wt(project, "feature-six-b")
    head = run_git(project, "rev-parse", "HEAD").strip()
    run_git(project, "worktree", "add", "--detach", str(wt), head)

    with pytest.raises(WorkspaceInconsistentError):
        _start(project).run("feature-six-b")


# --- CT-07 / CT-08: idempotency --------------------------------------------


def test_ct07_repeated_stop_idempotent(project: Path, run_git) -> None:
    _add(run_git, project, "feature-seven")
    first = _stop(project).run("feature-seven")
    before = _snapshot(project)
    second = _stop(project).run("feature-seven")

    assert first == second
    assert _snapshot(project) == before


def test_ct08_repeated_start_idempotent(project: Path, run_git) -> None:
    _add(run_git, project, "feature-eight")
    first = _start(project).run("feature-eight")
    second = _start(project).run("feature-eight")
    assert first == second


# --- CT-09: no artificial state file ---------------------------------------


def test_ct09_no_state_artifact(project: Path, run_git) -> None:
    _add(run_git, project, "feature-nine")
    before = sorted(str(p) for p in project.rglob("*"))
    _stop(project).run("feature-nine")
    _start(project).run("feature-nine")
    after = sorted(str(p) for p in project.rglob("*"))
    # AC-09: no new files created by start/stop.
    assert after == before


# --- CT-10: no process heuristics / no mutations ---------------------------


def test_ct10_no_git_mutations(project: Path, run_git) -> None:
    class _SpyRunner(GitRunner):
        def __init__(self, cwd) -> None:
            super().__init__(cwd)
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args, check=False, cwd=None):
            self.calls.append(tuple(args))
            return super().run(*args, check=check, cwd=cwd)

    _add(run_git, project, "feature-ten")
    spy = _SpyRunner(project)
    repo = GitRepository.from_root(project, runner=spy)
    service = StopWorkspaceService(resolve_project_config(project), repository=repo)
    service.run("feature-ten")

    forbidden_first = frozenset({"fetch", "pull", "push", "remote", "clone"})
    mutating_worktree = {"add", "remove", "prune", "move"}
    for argv in spy.calls:
        assert argv
        assert argv[0] not in forbidden_first, f"network command: {argv}"
        if argv[0] == "worktree":
            assert argv[1] not in mutating_worktree, f"mutating worktree: {argv}"
        assert not (argv[0] == "branch" and ("-d" in argv or "-D" in argv))
        assert argv[0] not in {"checkout", "reset", "clean"}, f"mutation: {argv}"


# --- CLI integration -------------------------------------------------------


def test_cli_stop_ready(project: Path, monkeypatch, run_git) -> None:
    _add(run_git, project, "feature-cli")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["stop", "feature-cli"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "target: feature-cli" in out
    assert "resources_stopped: 0" in out
    assert "no_op: true" in out


def test_cli_start_missing_maps_to_state_error(project: Path, monkeypatch) -> None:
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["start", "feature-absent"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.STATE_ERROR
    assert stdout.getvalue() == ""
    assert stderr.getvalue().startswith("error: ")
