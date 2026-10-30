"""Tests for the optional tmux capability (E5-S0) using a simulated runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import (
    CapabilityContext,
    CapabilityRegistry,
    CapabilityState,
)
from ramalio.capabilities.tmux import TmuxCapability, derive_session_name
from ramalio.capabilities.tmux.runtime import OWNER_ENV_KEY
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.errors import (
    CapabilityConfigInvalidError,
    CapabilityHookFailedError,
    TmuxSessionOwnershipError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.startstop import StartWorkspaceService, StopWorkspaceService
from ramalio.core.target import Target


class FakeTmuxRunner:
    """In-memory tmux simulation for deterministic tests."""

    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        # name -> {env: {}}
        self.sessions: dict[str, dict[str, str]] = {}

    @property
    def available(self) -> bool:
        return self._available

    def has_session(self, name: str) -> bool:
        return name in self.sessions

    def new_session(self, name: str, *, cwd: str | None = None) -> None:
        self.sessions[name] = {}

    def kill_session(self, name: str) -> None:
        self.sessions.pop(name, None)

    def set_session_env(self, name: str, key: str, value: str) -> None:
        self.sessions.setdefault(name, {})[key] = value

    def get_session_env(self, name: str, key: str) -> str | None:
        return self.sessions.get(name, {}).get(key)


def _config_body(extra: str) -> str:
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

[capabilities.tmux]
enabled = true
{extra}
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(
        git_repo_with_commit,
        _config_body('create_on_init = true\ndestroy_policy = "kill"\n'),
    )
    return git_repo_with_commit


def _ctx(project_root: Path, target: str) -> CapabilityContext:
    config = resolve_project_config(project_root)
    identity = build_workspace_naming(config).resolve(Target.from_trusted(target))
    return CapabilityContext(config=config, identity=identity)


def _registry(runner: FakeTmuxRunner) -> CapabilityRegistry:
    return CapabilityRegistry.with_capabilities([TmuxCapability(runner=runner)])


# --- naming (R3) -----------------------------------------------------------


def test_derive_session_name() -> None:
    assert derive_session_name("ramalio-{target}", "feat-x") == "ramalio-feat-x"
    with pytest.raises(CapabilityConfigInvalidError):
        derive_session_name("ramalio-{target}", "bad.name")  # '.' invalid


def test_missing_placeholder_rejected(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, _config_body('session_pattern = "static"\n'))
    cap = TmuxCapability(runner=FakeTmuxRunner())
    with pytest.raises(CapabilityConfigInvalidError):
        cap.validate_config(_ctx(git_repo_with_commit, "feat-a"))


# --- init creates session (R4) ---------------------------------------------


def test_create_on_init(project: Path) -> None:
    runner = FakeTmuxRunner()
    InitWorkspaceService(
        resolve_project_config(project), registry=_registry(runner)
    ).run("feat-a")
    assert runner.has_session("ramalio-feat-a")
    assert runner.get_session_env("ramalio-feat-a", OWNER_ENV_KEY) == "feat-a"


def test_init_idempotent(project: Path) -> None:
    runner = FakeTmuxRunner()
    reg = _registry(runner)
    InitWorkspaceService(resolve_project_config(project), registry=reg).run("feat-b")
    # Simulate a second start ensuring session (idempotent, no duplicate error).
    StartWorkspaceService(resolve_project_config(project), registry=reg).run("feat-b")
    assert list(runner.sessions.keys()) == ["ramalio-feat-b"]


# --- status (R6) -----------------------------------------------------------


def test_status_running_vs_missing(project: Path) -> None:
    runner = FakeTmuxRunner()
    cap = TmuxCapability(runner=runner)
    ctx = _ctx(project, "feat-c")
    assert cap.status(ctx).state == CapabilityState.STOPPED
    runner.new_session("ramalio-feat-c")
    runner.set_session_env("ramalio-feat-c", OWNER_ENV_KEY, "feat-c")
    assert cap.status(ctx).state == CapabilityState.ACTIVE


def test_status_tmux_unavailable(project: Path) -> None:
    cap = TmuxCapability(runner=FakeTmuxRunner(available=False))
    assert cap.status(_ctx(project, "feat-d")).state == CapabilityState.ERROR


# --- ownership (R10) -------------------------------------------------------


def test_ownership_conflict_blocks(project: Path) -> None:
    runner = FakeTmuxRunner()
    # A preexisting session with the derived name but no owner marker.
    runner.new_session("ramalio-feat-e")
    cap = TmuxCapability(runner=runner)
    ctx = _ctx(project, "feat-e")
    with pytest.raises(TmuxSessionOwnershipError):
        cap._ensure_session(ctx, ctx.identity)


def test_destroy_does_not_kill_unowned(project: Path) -> None:
    runner = FakeTmuxRunner()
    runner.new_session("ramalio-feat-f")  # unowned
    cap = TmuxCapability(runner=runner)
    ctx = _ctx(project, "feat-f")
    with pytest.raises(TmuxSessionOwnershipError):
        cap._kill_if_owned(ctx, ctx.identity)
    # Session preserved.
    assert runner.has_session("ramalio-feat-f")


# --- stop/destroy policies (R8/R9) -----------------------------------------


def test_stop_keep_by_default(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, _config_body("create_on_init = true\n"))
    runner = FakeTmuxRunner()
    reg = _registry(runner)
    InitWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=reg
    ).run("feat-g")
    StopWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=reg
    ).run("feat-g")
    # Default stop_policy keep -> session survives.
    assert runner.has_session("ramalio-feat-g")


def test_destroy_kill_removes_owned_session(project: Path) -> None:
    runner = FakeTmuxRunner()
    reg = _registry(runner)
    from ramalio.core.destroy import DestroyWorkspaceService

    InitWorkspaceService(resolve_project_config(project), registry=reg).run("feat-h")
    assert runner.has_session("ramalio-feat-h")
    DestroyWorkspaceService(resolve_project_config(project), registry=reg).run(
        "feat-h"
    )
    # destroy_policy kill -> owned session removed.
    assert not runner.has_session("ramalio-feat-h")


# --- doctor (R2) -----------------------------------------------------------


def test_doctor_detects_missing_tmux(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, _config_body("create_on_init = false\n"))
    from ramalio.core.doctor import CheckStatus, DoctorService

    registry = CapabilityRegistry.with_capabilities(
        [TmuxCapability(runner=FakeTmuxRunner(available=False))]
    )
    report = DoctorService(start=git_repo_with_commit, registry=registry).run()
    tmux_checks = [r for r in report.results if r.check_id == "TMUX_AVAILABLE"]
    assert tmux_checks and tmux_checks[0].status == CheckStatus.FAIL


# --- core still works without tmux -----------------------------------------


def test_core_works_without_tmux(git_repo_with_commit: Path, write_config) -> None:
    # No tmux capability enabled -> plain init works (default registry includes
    # tmux but it is disabled).
    write_config(
        git_repo_with_commit,
        """
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
""",
    )
    InitWorkspaceService(
        resolve_project_config(git_repo_with_commit)
    ).run("feat-plain")
    from ramalio.git.repository import GitRepository

    assert GitRepository.from_root(git_repo_with_commit).branch_exists("feat-plain")
