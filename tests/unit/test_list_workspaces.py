"""End-to-end and unit tests for `ramalio list` (E3-S0).

Covers CT-01..CT-10 and the acceptance criteria AC-01..AC-10 on real temporary
Git repositories with multiple worktrees.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.list_workspaces import (
    ListWorkspacesService,
    WorkspaceState,
    _BranchPatternMatcher,
)
from ramalio.core.result import ExitCode
from ramalio.git.repository import GitRepository
from ramalio.git.runner import GitRunner

# Branch pattern uses a literal prefix so reverse mapping is exercised
# meaningfully (spec/{target}).
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
pattern = "spec/{target}"
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _CONFIG_BODY)
    return git_repo_with_commit


def _service(project_root: Path) -> ListWorkspacesService:
    return ListWorkspacesService(resolve_project_config(project_root))


def _add_managed(run_git, project_root: Path, target: str) -> Path:
    """Add a canonical managed worktree for ``target`` (branch spec/<target>)."""

    wt = (project_root / ".local-wt" / target).resolve()
    run_git(project_root, "worktree", "add", "-b", f"spec/{target}", str(wt))
    return wt


# --- CT-01: no additional worktrees ----------------------------------------


def test_ct01_no_additional_worktrees(project: Path) -> None:
    listing = _service(project).run()
    # AC-08: success with no managed workspaces (only the main checkout exists).
    assert listing.items == ()
    assert listing.has_managed_workspaces is False
    assert "No managed workspaces" in listing.render_lines()


# --- CT-02: one ready workspace --------------------------------------------


def test_ct02_one_ready_workspace(project: Path, run_git) -> None:
    _add_managed(run_git, project, "feature-one")

    listing = _service(project).run()
    assert len(listing.items) == 1
    item = listing.items[0]
    # AC-01/AC-03: recognized and target derived from reversible naming.
    assert item.recognized is True
    assert item.target == "feature-one"
    assert item.branch == "spec/feature-one"
    assert item.state == WorkspaceState.READY


# --- CT-03: two targets sorted ascending -----------------------------------


def test_ct03_two_targets_sorted(project: Path, run_git) -> None:
    _add_managed(run_git, project, "bravo")
    _add_managed(run_git, project, "alpha")

    listing = _service(project).run()
    targets = [i.target for i in listing.items]
    # AC-09: deterministic ascending target order.
    assert targets == ["alpha", "bravo"]


# --- CT-04: dirty workspace ------------------------------------------------


def test_ct04_dirty_workspace(project: Path, run_git) -> None:
    wt = _add_managed(run_git, project, "feature-dirty")
    (wt / "new.txt").write_text("work\n", encoding="utf-8")

    listing = _service(project).run()
    # AC-04: dirty differs from ready.
    assert listing.items[0].state == WorkspaceState.DIRTY


# --- CT-05: detached worktree ----------------------------------------------


def test_ct05_detached_worktree(project: Path, run_git) -> None:
    wt = (project / ".local-wt" / "detached-wt").resolve()
    head = run_git(project, "rev-parse", "HEAD").strip()
    run_git(project, "worktree", "add", "--detach", str(wt), head)

    listing = _service(project).run()
    item = listing.items[0]
    # AC-05: detached, no invented target.
    assert item.state == WorkspaceState.DETACHED
    assert item.target is None
    assert item.recognized is False


# --- CT-06: unrecognized branch pattern ------------------------------------


def test_ct06_unrecognized_branch(project: Path, run_git) -> None:
    wt = (project / ".local-wt" / "random").resolve()
    run_git(project, "worktree", "add", "-b", "totally-unrelated", str(wt))

    listing = _service(project).run()
    item = listing.items[0]
    # AC (R5): branch does not match spec/{target} -> UNRECOGNIZED.
    assert item.state == WorkspaceState.UNRECOGNIZED
    assert item.target is None
    assert item.branch == "totally-unrelated"


# --- CT-07: path mismatch -> inconsistent ----------------------------------


def test_ct07_path_mismatch_inconsistent(project: Path, run_git) -> None:
    # Branch derives target "feature-x" but worktree lives at a non-canonical
    # path.
    wt = (project / ".local-wt" / "wrong-place").resolve()
    run_git(project, "worktree", "add", "-b", "spec/feature-x", str(wt))

    listing = _service(project).run()
    item = listing.items[0]
    # AC-06: inconsistency surfaced with a stable reason, target still reported.
    assert item.state == WorkspaceState.INCONSISTENT
    assert item.target == "feature-x"
    assert item.reason == "WORKTREE_PATH_MISMATCH"
    assert item.recognized is False


# --- CT-08: prunable worktree ----------------------------------------------


def test_ct08_prunable_worktree(project: Path, run_git) -> None:
    wt = _add_managed(run_git, project, "feature-prune")
    # Remove the worktree directory from disk without telling Git -> prunable /
    # missing path.  list must report it, never prune it.
    import shutil

    shutil.rmtree(wt)

    listing = _service(project).run()
    item = listing.items[0]
    # AC-07: prunable visible, not repaired.
    assert item.state == WorkspaceState.PRUNABLE
    # The worktree is still registered (list did not prune).
    assert any(w.path == wt for w in GitRepository.from_root(project).list_worktrees())


# --- CT-09: main checkout on a similar branch is not a workspace -----------


def test_ct09_main_checkout_not_a_workspace(project: Path, run_git) -> None:
    # Rename the main checkout's branch to something matching spec/{target}.
    run_git(project, "checkout", "-q", "-b", "spec/main-like")

    listing = _service(project).run()
    # AC-02: the main checkout is never presented as a managed target.
    assert listing.items == ()


# --- CT-10: read-only (no mutations) ---------------------------------------


def test_ct10_list_issues_no_mutations(project: Path, run_git) -> None:
    class _SpyRunner(GitRunner):
        def __init__(self, cwd) -> None:
            super().__init__(cwd)
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args, check=False, cwd=None):
            self.calls.append(tuple(args))
            return super().run(*args, check=check, cwd=cwd)

    _add_managed(run_git, project, "feature-ro")
    spy = _SpyRunner(project)
    repo = GitRepository.from_root(project, runner=spy)
    service = ListWorkspacesService(resolve_project_config(project), repository=repo)
    service.run()

    forbidden_first = frozenset({"fetch", "pull", "push", "remote", "clone"})
    mutating_worktree = {"add", "remove", "prune", "move", "lock", "unlock"}
    for argv in spy.calls:
        assert argv
        assert argv[0] not in forbidden_first, f"network command: {argv}"
        if argv[0] == "worktree":
            assert argv[1] == "list", f"mutating worktree command: {argv}"
        assert argv[0] != "branch" or "-d" not in argv and "-D" not in argv


# --- reverse mapping unit checks (T2/T9) -----------------------------------


def test_branch_matcher_extracts_target() -> None:
    m = _BranchPatternMatcher("spec/{target}")
    assert m.extract("spec/feature-123") == "feature-123"
    assert m.extract("other/feature-123") is None
    assert m.extract("spec/") is None


def test_branch_matcher_plain_target_pattern() -> None:
    m = _BranchPatternMatcher("{target}")
    assert m.extract("feature-abc") == "feature-abc"


# --- CLI integration -------------------------------------------------------


def test_cli_list_empty_is_success(project: Path, monkeypatch) -> None:
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["list"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    assert "No managed workspaces" in stdout.getvalue()
    assert stderr.getvalue() == ""


def test_cli_list_shows_table(project: Path, monkeypatch, run_git) -> None:
    _add_managed(run_git, project, "feature-cli")
    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["list"], stdout=stdout, stderr=stderr)

    assert code == ExitCode.OK
    out = stdout.getvalue()
    assert "TARGET" in out
    assert "feature-cli" in out
    assert "spec/feature-cli" in out
    assert "READY" in out
