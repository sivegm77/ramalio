"""E10-S0 — workspace provisioning contract tests.

Proves that optional provisioning capabilities participate in the existing
lifecycle for ``init`` (via the existing ``after_init`` event) and ``adopt``
(via the single new ``after_adopt`` event) while reusing the existing registry,
HookRunner, LifecycleTransaction, ownership and rollback (E10-S0 R2..R9).

Covers the spec's acceptance criteria:

* AC-02 fake capability receives AFTER_INIT.
* AC-03 fake capability receives AFTER_ADOPT in both adopt modes.
* AC-04 AFTER_ADOPT failure in created-worktree reverts the created worktree and
  the capability's own mutations.
* AC-05 AFTER_ADOPT failure in existing-worktree preserves preexisting Git.
* AC-06 a preexisting capability resource is not compensated.
* AC-08 only AFTER_ADOPT is added (no BEFORE_ADOPT); event classification holds.

Git-only regression (AC-01) is asserted here for adopt and the whole suite +
conformance cover AC-10.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import BaseCapability, CapabilityRegistry
from ramalio.config.loader import resolve_project_config
from ramalio.core.adopt import AdoptWorkspaceService
from ramalio.core.errors import CapabilityHookFailedError
from ramalio.core.init import InitWorkspaceService
from ramalio.git.repository import GitRepository
from ramalio.hooks import HookResult, LifecycleEvent

_CONFIG = """
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

[capabilities.provisioner]
enabled = true
"""

_CLEAN_CONFIG = """
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
    write_config(git_repo_with_commit, _CONFIG)
    return git_repo_with_commit


@pytest.fixture
def project_two(git_repo_with_commit: Path, write_config) -> Path:
    write_config(
        git_repo_with_commit,
        _CONFIG + "\n[capabilities.provisioner2]\nenabled = true\n",
    )
    return git_repo_with_commit


@pytest.fixture
def clean_project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _CLEAN_CONFIG)
    return git_repo_with_commit


def _wt_path(root: Path, target: str) -> Path:
    return (root / ".local-wt" / target).resolve()


# --- fake provisioning capabilities ----------------------------------------


class _Provisioner(BaseCapability):
    """Records provisioning events and reports a compensable change on setup.

    ``changed`` is reported on setup events (``after_*``) so the capability's
    own mutation is journaled as a compensable transaction step, mirroring how a
    real provisioning capability behaves.
    """

    capability_name = "provisioner"

    def __init__(self, log: list[str], *, changed: bool = True) -> None:
        self._log = log
        self._changed = changed

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"handle:{event}")
        changed = self._changed and event.startswith("after_")
        return HookResult(
            capability=self.capability_name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary="ok",
            compensation_available=changed,
        )

    def compensate(self, event: str, context: object) -> None:
        self._log.append(f"compensate:{event}")


class _FailAfterAdopt(BaseCapability):
    """Fails specifically on ``after_adopt`` to exercise rollback."""

    capability_name = "provisioner"

    def __init__(self, log: list[str] | None = None) -> None:
        self._log = log if log is not None else []

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"handle:{event}")
        if event == "after_adopt":
            raise RuntimeError("boom after adopt")
        return None


def _registry(*caps) -> CapabilityRegistry:
    return CapabilityRegistry.with_capabilities(caps)


# --- AC-08: event classification (only AFTER_ADOPT added) ------------------


def test_ac08_after_adopt_event_classification() -> None:
    event = LifecycleEvent.AFTER_ADOPT
    assert event.value == "after_adopt"
    # Recognized as an "after" (setup) event by prefix, never a teardown.
    assert event.is_after is True
    assert event.is_before is False
    assert event.is_teardown is False


def test_ac08_no_before_adopt_event_exists() -> None:
    # Exactly AFTER_ADOPT is added; BEFORE_ADOPT must not exist (spec 6.1/AC-08).
    names = {e.name for e in LifecycleEvent}
    assert "AFTER_ADOPT" in names
    assert "BEFORE_ADOPT" not in names


# --- AC-02: capability receives AFTER_INIT (init uses existing event) ------


def test_ac02_init_runs_after_init_provisioning(project: Path) -> None:
    log: list[str] = []
    registry = _registry(_Provisioner(log))
    InitWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-init")

    # R2: init uses AFTER_INIT (no new init event); provisioning runs after the
    # worktree exists and before init returns success.
    assert "handle:after_init" in log
    repo = GitRepository.from_root(project)
    assert repo.branch_exists("feat-init")


# --- AC-03: capability receives AFTER_ADOPT in both adopt modes ------------


def test_ac03_after_adopt_runs_in_created_worktree_mode(project: Path, run_git) -> None:
    log: list[str] = []
    run_git(project, "branch", "feat-created", "main")
    registry = _registry(_Provisioner(log))

    outcome = AdoptWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-created")

    assert outcome.adoption_mode == "created-worktree"
    assert "handle:after_adopt" in log
    # Provisioning did not receive any before_adopt (no such event).
    assert not any(e.endswith("before_adopt") for e in log)


def test_ac03_after_adopt_runs_in_existing_worktree_mode(
    project: Path, run_git
) -> None:
    log: list[str] = []
    wt = _wt_path(project, "feat-existing")
    run_git(project, "worktree", "add", "-b", "feat-existing", str(wt))
    registry = _registry(_Provisioner(log))

    outcome = AdoptWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-existing")

    assert outcome.adoption_mode == "existing-worktree"
    assert "handle:after_adopt" in log


# --- AC-04: AFTER_ADOPT failure in created-worktree reverts worktree -------


def test_ac04_after_adopt_failure_created_worktree_rolls_back(
    project: Path, run_git
) -> None:
    run_git(project, "branch", "feat-fail-created", "main")
    registry = _registry(_FailAfterAdopt())

    with pytest.raises(CapabilityHookFailedError):
        AdoptWorkspaceService(
            resolve_project_config(project), registry=registry
        ).run("feat-fail-created")

    repo = GitRepository.from_root(project)
    # The worktree this adopt created is retired by the transaction rollback,
    # while the preexisting branch is preserved (R5/AC-04).
    assert repo.get_worktree_by_path(_wt_path(project, "feat-fail-created")) is None
    assert repo.branch_exists("feat-fail-created")


def test_ac04_after_adopt_failure_compensates_capability_mutation(
    project_two: Path, run_git
) -> None:
    """A capability that mutated (recorded a compensable change) before a later
    failing capability must be compensated LIFO under the same transaction."""

    log: list[str] = []
    run_git(project_two, "branch", "feat-comp", "main")
    # First capability records a compensable after_adopt change; second fails.
    registry = _registry(
        _NamedProvisioner(log, name="provisioner"),
        _NamedFailAfterAdopt(log, name="provisioner2"),
    )

    with pytest.raises(CapabilityHookFailedError):
        AdoptWorkspaceService(
            resolve_project_config(project_two), registry=registry
        ).run("feat-comp")

    # provisioner's successful after_adopt change is compensated.
    assert "provisioner:compensate:after_adopt" in log
    # And the created worktree is still rolled back.
    repo = GitRepository.from_root(project_two)
    assert repo.get_worktree_by_path(_wt_path(project_two, "feat-comp")) is None
    assert repo.branch_exists("feat-comp")


# --- AC-05: AFTER_ADOPT failure in existing-worktree preserves Git ---------


def test_ac05_after_adopt_failure_existing_worktree_preserves_git(
    project: Path, run_git
) -> None:
    wt = _wt_path(project, "feat-fail-existing")
    run_git(project, "worktree", "add", "-b", "feat-fail-existing", str(wt))
    (wt / "local-work.txt").write_text("keep me\n", encoding="utf-8")
    registry = _registry(_FailAfterAdopt())

    with pytest.raises(CapabilityHookFailedError):
        AdoptWorkspaceService(
            resolve_project_config(project), registry=registry
        ).run("feat-fail-existing")

    repo = GitRepository.from_root(project)
    # The preexisting worktree, branch and local work are untouched: the
    # existing-worktree transaction only ever records capability mutations, so
    # rollback never touches Git (AC-05).
    registered = repo.get_worktree_by_path(wt)
    assert registered is not None
    assert registered.branch == "feat-fail-existing"
    assert (wt / "local-work.txt").read_text(encoding="utf-8") == "keep me\n"


# --- AC-06: preexisting capability resource is not compensated -------------


def test_ac06_preexisting_resource_not_compensated(project_two: Path, run_git) -> None:
    """A capability that observed its resource already existed reports
    ``changed=False``; its (absent) mutation must never be compensated even when
    a later capability fails the after_adopt event (R7/AC-06)."""

    log: list[str] = []
    run_git(project_two, "branch", "feat-preexist", "main")
    registry = _registry(
        # This capability observed a preexisting resource: changed=False.
        _NamedProvisioner(log, name="provisioner", changed=False),
        # This one fails after_adopt, triggering rollback.
        _NamedFailAfterAdopt(log, name="provisioner2"),
    )

    with pytest.raises(CapabilityHookFailedError):
        AdoptWorkspaceService(
            resolve_project_config(project_two), registry=registry
        ).run("feat-preexist")

    # The unchanged capability's resource is never compensated (R7/AC-06).
    assert "provisioner:compensate:after_adopt" not in log


# --- AC-01: Git-only adopt is unchanged ------------------------------------


def test_ac01_git_only_adopt_unchanged_created(clean_project: Path, run_git) -> None:
    run_git(clean_project, "branch", "feat-git-only", "main")
    outcome = AdoptWorkspaceService(
        resolve_project_config(clean_project)
    ).run("feat-git-only")

    assert outcome.adoption_mode == "created-worktree"
    assert outcome.git_dirty is False
    repo = GitRepository.from_root(clean_project)
    assert (
        repo.get_worktree_by_path(_wt_path(clean_project, "feat-git-only"))
        is not None
    )


def test_ac01_git_only_adopt_unchanged_existing(clean_project: Path, run_git) -> None:
    wt = _wt_path(clean_project, "feat-git-existing")
    run_git(clean_project, "worktree", "add", "-b", "feat-git-existing", str(wt))

    before = _snapshot(clean_project)
    outcome = AdoptWorkspaceService(
        resolve_project_config(clean_project)
    ).run("feat-git-existing")

    # No capabilities enabled: existing-worktree adopt mutates nothing at all.
    assert outcome.adoption_mode == "existing-worktree"
    assert _snapshot(clean_project) == before


# --- named fakes for multi-capability ordering -----------------------------


class _NamedProvisioner(_Provisioner):
    def __init__(self, log: list[str], *, name: str, changed: bool = True) -> None:
        super().__init__(log, changed=changed)
        self.capability_name = name

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"{self.capability_name}:handle:{event}")
        changed = self._changed and event.startswith("after_")
        return HookResult(
            capability=self.capability_name,
            event=LifecycleEvent(event),
            success=True,
            changed=changed,
            summary="ok",
            compensation_available=changed,
        )

    def compensate(self, event: str, context: object) -> None:
        self._log.append(f"{self.capability_name}:compensate:{event}")


class _NamedFailAfterAdopt(BaseCapability):
    def __init__(self, log: list[str], *, name: str) -> None:
        self.capability_name = name
        self._log = log

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"{self.capability_name}:handle:{event}")
        if event == "after_adopt":
            raise RuntimeError("boom after adopt")
        return None


# --- helpers ---------------------------------------------------------------


def _snapshot(root: Path) -> tuple:
    import subprocess

    repo = GitRepository.from_root(root)
    branches_raw = subprocess.run(
        ["git", "-C", str(root), "branch"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    branches = tuple(
        sorted(
            line.strip().lstrip("* ").strip()
            for line in branches_raw.splitlines()
            if line.strip()
        )
    )
    worktrees = tuple(sorted(str(w.path) for w in repo.list_worktrees()))
    local_wt = root / ".local-wt"
    tree = (
        tuple(sorted(str(p) for p in local_wt.rglob("*"))) if local_wt.exists() else ()
    )
    return branches, worktrees, tree
