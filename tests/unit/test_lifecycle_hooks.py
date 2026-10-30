"""Tests for lifecycle hooks connecting capabilities to the lifecycle (E4-S1).

Uses fake capabilities to prove ordering, before/after fail behavior,
compensation and error boundaries, and that the CLI/core lifecycle stays free
of capability-specific logic (AC-01..AC-08).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import BaseCapability, CapabilityRegistry
from ramalio.config.loader import resolve_project_config
from ramalio.core.adopt import AdoptWorkspaceService  # noqa: F401 (import sanity)
from ramalio.core.destroy import DestroyWorkspaceService
from ramalio.core.errors import CapabilityHookFailedError
from ramalio.core.init import InitWorkspaceService
from ramalio.core.startstop import (
    StartWorkspaceService,
    StopWorkspaceService,
)
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

[capabilities.recorder]
enabled = true
"""

_CONFIG_TWO = _CONFIG + "\n[capabilities.recorder2]\nenabled = true\n"


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _CONFIG)
    return git_repo_with_commit


@pytest.fixture
def project_two(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _CONFIG_TWO)
    return git_repo_with_commit


# --- fake capabilities ------------------------------------------------------


class _RecorderCapability(BaseCapability):
    """Records the sequence of events it receives (order proof)."""

    capability_name = "recorder"

    def __init__(self, log: list[str], *, name: str = "recorder") -> None:
        self.capability_name = name
        self._log = log

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"{self.capability_name}:{event}")
        # Report a compensable change on 'after' events so compensation can be
        # exercised.
        changed = event.startswith("after_")
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


class _FailBeforeInit(BaseCapability):
    capability_name = "recorder"

    def handle(self, event: str, context: object) -> object:
        if event == "before_init":
            raise RuntimeError("boom before init")
        return None


class _FailAfterInit(BaseCapability):
    capability_name = "recorder"

    def handle(self, event: str, context: object) -> object:
        if event == "after_init":
            raise RuntimeError("boom after init")
        return None


class _CompensatingStart(BaseCapability):
    capability_name = "recorder"

    def __init__(self, log: list[str], *, name: str, fail_after: bool = False) -> None:
        self.capability_name = name
        self._log = log
        self._fail_after = fail_after

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"{self.capability_name}:{event}")
        if event == "after_start" and self._fail_after:
            raise RuntimeError("boom after start")
        changed = event.startswith("after_")
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


def _registry(*caps) -> CapabilityRegistry:
    return CapabilityRegistry.with_capabilities(caps)


# --- AC-01: fake capability receives before/after init ---------------------


def test_ac01_init_runs_before_and_after(project: Path) -> None:
    log: list[str] = []
    registry = _registry(_RecorderCapability(log))
    service = InitWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    service.run("feature-one")

    assert "recorder:before_init" in log
    assert "recorder:after_init" in log
    assert log.index("recorder:before_init") < log.index("recorder:after_init")

    # The Git workspace was actually created (core lifecycle still authoritative).
    repo = GitRepository.from_root(project)
    assert repo.branch_exists("feature-one")


# --- AC-02: before failure blocks core mutation ----------------------------


def test_ac02_before_init_failure_blocks_creation(project: Path) -> None:
    registry = _registry(_FailBeforeInit())
    service = InitWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feature-two")

    # AC-02: nothing created.
    repo = GitRepository.from_root(project)
    assert not repo.branch_exists("feature-two")
    assert repo.get_worktree_by_path(
        (project / ".local-wt" / "feature-two").resolve()
    ) is None


# --- AC-03: after init failure triggers controlled rollback ----------------


def test_ac03_after_init_failure_rolls_back(project: Path) -> None:
    registry = _registry(_FailAfterInit())
    service = InitWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feature-three")

    # AC-03: the Git worktree/branch created by this init are rolled back.
    repo = GitRepository.from_root(project)
    assert not repo.branch_exists("feature-three")
    assert repo.get_worktree_by_path(
        (project / ".local-wt" / "feature-three").resolve()
    ) is None


# --- AC-06: deterministic order across two capabilities --------------------


def test_ac06_deterministic_order(project_two: Path) -> None:
    log: list[str] = []
    registry = _registry(
        _RecorderCapability(log, name="recorder"),
        _RecorderCapability(log, name="recorder2"),
    )
    service = InitWorkspaceService(
        resolve_project_config(project_two), registry=registry
    )
    service.run("feature-order")

    before = [e for e in log if e.endswith("before_init")]
    after = [e for e in log if e.endswith("after_init")]
    assert before == ["recorder:before_init", "recorder2:before_init"]
    assert after == ["recorder:after_init", "recorder2:after_init"]


# --- AC-04: start compensation in reverse order ----------------------------


def test_ac04_after_start_failure_compensates_reverse(project_two: Path) -> None:
    log: list[str] = []
    # recorder succeeds (records a compensable after_start change); recorder2
    # fails on after_start. Compensation must run in reverse of success order.
    registry = _registry(
        _CompensatingStart(log, name="recorder"),
        _CompensatingStart(log, name="recorder2", fail_after=True),
    )
    # Create a real READY workspace first so start is addressable. The config
    # enables `recorder`/`recorder2`, so init must run under a registry that
    # knows them (E4-S0 R13 fail-closed on unknown capabilities); use benign
    # no-op recorders for the setup so start owns the interesting behavior.
    InitWorkspaceService(
        resolve_project_config(project_two),
        registry=_registry(
            _RecorderCapability([], name="recorder"),
            _RecorderCapability([], name="recorder2"),
        ),
    ).run("feature-comp")

    service = StartWorkspaceService(
        resolve_project_config(project_two), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feature-comp")

    # recorder's successful after_start action is compensated (recorder2 failed
    # before recording a compensable success).
    assert "recorder:compensate:after_start" in log


# --- AC-05: before destroy failure preserves worktree ----------------------


class _FailBeforeDestroy(BaseCapability):
    capability_name = "recorder"

    def handle(self, event: str, context: object) -> object:
        if event == "before_destroy":
            raise RuntimeError("boom before destroy")
        return None


def test_ac05_before_destroy_failure_preserves_worktree(project: Path) -> None:
    # Build a clean workspace then attempt destroy with a failing before_destroy
    # hook. The config enables `recorder`, so the setup init must run under a
    # registry that knows it (fail-closed on unknown capabilities); a benign
    # no-op recorder keeps the setup free of interesting behavior.
    InitWorkspaceService(
        resolve_project_config(project),
        registry=_registry(_RecorderCapability([])),
    ).run("feature-five")
    registry = _registry(_FailBeforeDestroy())
    service = DestroyWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feature-five")

    # AC-05: worktree preserved because before_destroy blocked the removal.
    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(
        (project / ".local-wt" / "feature-five").resolve()
    ) is not None
    assert repo.branch_exists("feature-five")


# --- AC-07: capability exception maps to stable error ----------------------


def test_ac07_exception_maps_to_stable_error(project: Path) -> None:
    registry = _registry(_FailBeforeInit())
    service = InitWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError) as exc:
        service.run("feature-seven")
    assert exc.value.capability == "recorder"
    assert exc.value.event == "before_init"
    assert exc.value.code == "CAPABILITY_HOOK_FAILED"


# --- stop hooks run around the no-op ----------------------------------------


def test_stop_runs_hooks(project: Path) -> None:
    log: list[str] = []
    # The config enables `recorder`; init must run under a registry that knows
    # it (fail-closed). Use a benign no-op recorder for the setup init.
    InitWorkspaceService(
        resolve_project_config(project),
        registry=_registry(_RecorderCapability([])),
    ).run("feature-stop")
    registry = _registry(_RecorderCapability(log))
    service = StopWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    service.run("feature-stop")
    assert "recorder:before_stop" in log
    assert "recorder:after_stop" in log


# --- default (empty registry) keeps pure Git-only behavior -----------------


def test_no_registry_is_pure_noop(git_repo_with_commit: Path, write_config) -> None:
    # A project WITHOUT any capabilities: start/stop remain pure Git-only no-ops
    # with the default empty registry.
    clean_config = """
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
    write_config(git_repo_with_commit, clean_config)
    InitWorkspaceService(
        resolve_project_config(git_repo_with_commit)
    ).run("feature-plain")
    out = StopWorkspaceService(
        resolve_project_config(git_repo_with_commit)
    ).run("feature-plain")
    assert out.no_op is True
    assert out.resources_stopped == 0
