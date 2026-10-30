"""Tests for the runtime capability contract and the none/fake drivers (E6-S0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import (
    CapabilityContext,
    CapabilityRegistry,
    CapabilityState,
)
from ramalio.capabilities.runtime import (
    RuntimeCapability,
    RuntimeDoctorCheck,
    RuntimeResult,
    RuntimeState,
    RuntimeWorkspace,
)
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.errors import RuntimeDriverUnknownError, RuntimeStartFailedError
from ramalio.core.init import InitWorkspaceService
from ramalio.core.startstop import StartWorkspaceService, StopWorkspaceService
from ramalio.core.target import Target


def _config_body(runtime: str = "") -> str:
    return f"""
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{{target}}"

[branch]
pattern = "{{target}}"
{runtime}
"""


def _ctx(project_root: Path, target: str = "feat-a") -> CapabilityContext:
    config = resolve_project_config(project_root)
    identity = build_workspace_naming(config).resolve(Target.from_trusted(target))
    return CapabilityContext(config=config, identity=identity)


# --- a fake driver for tests -----------------------------------------------


class FakeDriver:
    def __init__(self) -> None:
        self.running = False
        self.cleaned = False
        self.fail_start = False

    @property
    def name(self) -> str:
        return "fake"

    def doctor(self, workspace):
        return (RuntimeDoctorCheck("RUNTIME_FAKE", True, "fake ready"),)

    def start(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        if self.fail_start:
            from ramalio.core.errors import OperationError

            raise OperationError("fake start failure")
        self.running = True
        return RuntimeResult(RuntimeState.RUNNING, "started")

    def stop(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        self.running = False
        return RuntimeResult(RuntimeState.STOPPED, "stopped")

    def status(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        return RuntimeResult(
            RuntimeState.RUNNING if self.running else RuntimeState.STOPPED,
            "running" if self.running else "stopped",
        )

    def cleanup(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        self.cleaned = True
        self.running = False
        return RuntimeResult(RuntimeState.STOPPED, "cleaned up")


def _fake_capability(driver: FakeDriver) -> RuntimeCapability:
    return RuntimeCapability(drivers={"fake": lambda _o: driver, "none": None.__class__})


# --- AC-01: no runtime -> none driver, core works --------------------------


def test_ac01_none_driver_default(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, _config_body())  # no runtime section
    cap = RuntimeCapability()
    ctx = _ctx(git_repo_with_commit)
    # Not enabled without a runtime section -> DISABLED.
    assert cap.status(ctx).state == CapabilityState.DISABLED


def test_none_driver_explicit(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "none"\n'),
    )
    cap = RuntimeCapability()
    status = cap.status(_ctx(git_repo_with_commit))
    # none driver -> NOT_APPLICABLE -> READY capability state.
    assert status.state == CapabilityState.READY


# --- unknown driver --------------------------------------------------------


def test_unknown_driver(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "mystery"\n'),
    )
    cap = RuntimeCapability()
    with pytest.raises(RuntimeDriverUnknownError):
        cap.validate_config(_ctx(git_repo_with_commit))


# --- AC-02..AC-05: fake driver lifecycle & idempotency ---------------------


def test_ac02_fake_driver_start_stop(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "fake"\n'),
    )
    driver = FakeDriver()
    registry = CapabilityRegistry.with_capabilities(
        [RuntimeCapability(drivers={"fake": lambda _o: driver})]
    )
    InitWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    ).run("feat-a")
    StartWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    ).run("feat-a")
    assert driver.running is True
    StopWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    ).run("feat-a")
    assert driver.running is False


def test_ac03_ac04_idempotent(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "fake"\n'),
    )
    driver = FakeDriver()
    registry = CapabilityRegistry.with_capabilities(
        [RuntimeCapability(drivers={"fake": lambda _o: driver})]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-b")
    StartWorkspaceService(cfg, registry=registry).run("feat-b")
    StartWorkspaceService(cfg, registry=registry).run("feat-b")  # repeated
    assert driver.running is True
    StopWorkspaceService(cfg, registry=registry).run("feat-b")
    StopWorkspaceService(cfg, registry=registry).run("feat-b")  # repeated
    assert driver.running is False


# --- AC-06: status integration ---------------------------------------------


def test_ac06_status_reports_running(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "fake"\n'),
    )
    driver = FakeDriver()
    driver.running = True
    cap = RuntimeCapability(drivers={"fake": lambda _o: driver})
    status = cap.status(_ctx(git_repo_with_commit))
    assert status.state == CapabilityState.ACTIVE


# --- AC-07: doctor -----------------------------------------------------------


def test_ac07_doctor_check(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "fake"\n'),
    )
    driver = FakeDriver()
    cap = RuntimeCapability(drivers={"fake": lambda _o: driver})
    checks = cap.doctor_checks(_ctx(git_repo_with_commit))
    assert any(c.check_id == "RUNTIME_FAKE" for c in checks)


# --- start failure maps to stable error + compensation ---------------------


def test_start_failure_maps_to_runtime_error(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "fake"\n'),
    )
    driver = FakeDriver()
    driver.fail_start = True
    registry = CapabilityRegistry.with_capabilities(
        [RuntimeCapability(drivers={"fake": lambda _o: driver})]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-fail")
    from ramalio.core.errors import CapabilityHookFailedError

    with pytest.raises(CapabilityHookFailedError):
        StartWorkspaceService(cfg, registry=registry).run("feat-fail")


# --- destroy runs cleanup --------------------------------------------------


def test_destroy_runs_cleanup(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.runtime]\ndriver = "fake"\n'),
    )
    driver = FakeDriver()
    registry = CapabilityRegistry.with_capabilities(
        [RuntimeCapability(drivers={"fake": lambda _o: driver})]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-destroy")
    from ramalio.core.destroy import DestroyWorkspaceService

    DestroyWorkspaceService(cfg, registry=registry).run("feat-destroy")
    assert driver.cleaned is True
