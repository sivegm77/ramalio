"""Adversarial regression tests for the second audit round (E7-S0).

Two transversal principles under test:

1. ownership is tri-state (OWNED / NOT_OWNED / UNKNOWN); UNKNOWN must never be
   collapsed into "not owned" and must never destroy evidence; and
2. an operation that mutates *before* raising must enter the
   ``LifecycleTransaction`` so rollback can compensate or diagnose it.

Covers findings H1..H7 of the round-2 audit with real Git repos (H1) and fake
drivers/providers (H2..H7); no real Docker/tmux/zrok are used.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ramalio.capabilities import CapabilityRegistry
from ramalio.capabilities.runtime.base import (
    RuntimeResult,
    RuntimeState,
    RuntimeWorkspace,
)
from ramalio.capabilities.runtime.capability import RuntimeCapability
from ramalio.capabilities.runtime.docker_compose import DockerComposeDriver
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    AdoptGitOperationFailedError,
    AdoptRollbackIncompleteError,
    GitCommandError,
    RuntimeStartFailedError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.naming import ResolvedWorkspaceIdentity
from ramalio.core.target import Target
from ramalio.git.lifecycle import GitWriter
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
    write_config(git_repo_with_commit, _CONFIG_BODY)
    return git_repo_with_commit


# ---------------------------------------------------------------------------
# H1 — adopt rollback must preserve a detached worktree (ownership not provable)
# ---------------------------------------------------------------------------


class _MutateDetachedThenFailWriter(GitWriter):
    """Attaches a DETACHED worktree at the target path and then fails, modeling
    a Git operation that mutated (detached, not on our branch) before exiting
    non-zero."""

    def add_worktree_for_branch(self, *, branch: str, worktree_path: Path) -> None:
        # Create a detached worktree at the canonical path (NOT on our branch).
        self._runner_add_detached(worktree_path)
        raise GitCommandError(
            "simulated post-mutation failure", args=("worktree", "add")
        )

    def _runner_add_detached(self, worktree_path: Path) -> None:
        subprocess.run(
            [
                "git",
                "-C",
                str(self._root),
                "worktree",
                "add",
                "--detach",
                str(worktree_path),
                "HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def test_h1_adopt_preserves_detached_worktree_on_rollback(
    project: Path, run_git
) -> None:
    from ramalio.core.adopt import AdoptWorkspaceService

    run_git(project, "branch", "feat-r2h1", "main")

    config = resolve_project_config(project)
    writer = _MutateDetachedThenFailWriter(project)
    service = AdoptWorkspaceService(config, writer=writer)

    # adopt fails; rollback must NOT force-remove the detached worktree because
    # ownership is not demonstrable -> it surfaces AdoptRollbackIncompleteError
    # (in addition to the primary Git failure) and preserves the resource.
    with pytest.raises((AdoptRollbackIncompleteError, AdoptGitOperationFailedError)):
        service.run("feat-r2h1")

    repo = GitRepository.from_root(project)
    resolved_path = (project / ".local-wt" / "feat-r2h1").resolve()
    wt = repo.get_worktree_by_path(resolved_path)
    assert wt is not None, "detached worktree was wrongly removed by adopt rollback"
    # The preexisting branch is preserved (never part of rollback).
    assert repo.branch_exists("feat-r2h1")


# ---------------------------------------------------------------------------
# Fake docker runner for H2/H3/H7 (controls ps/up/down outcomes)
# ---------------------------------------------------------------------------


class _ConfigurableDockerRunner:
    def __init__(
        self,
        *,
        ps_running_rc: int = 0,
        running_ids: str = "",
        all_ids: str = "",
        ps_json: str | None = None,
    ) -> None:
        self._ps_running_rc = ps_running_rc
        self._running_ids = running_ids
        self._all_ids = all_ids
        self._ps_json = ps_json
        self.calls: list[tuple[str, ...]] = []

    @property
    def available(self) -> bool:
        return True

    def compose_available(self) -> bool:
        return True

    def compose(self, project, compose_file, *args, cwd, env=None, extra_files=()):
        self.calls.append(tuple(args))
        if args and args[0] == "ps":
            if "--format" in args and "json" in args:
                return subprocess.CompletedProcess([], 0, self._ps_json or "", "")
            if "--all" in args:
                return subprocess.CompletedProcess([], 0, self._all_ids, "")
            # running probe (--status=running --quiet)
            return subprocess.CompletedProcess(
                [], self._ps_running_rc, self._running_ids, ""
            )
        # up / down / stop succeed.
        return subprocess.CompletedProcess([], 0, "", "")


def _workspace(tmp_path: Path, target: str = "alpha") -> RuntimeWorkspace:
    wt = tmp_path / target
    wt.mkdir(exist_ok=True)
    from pathlib import PurePosixPath

    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted(target),
        branch_name=target,
        worktree_path=PurePosixPath(".local-wt") / target,
    )
    return RuntimeWorkspace(
        target=target, worktree_path=wt, identity=identity, repository_root=tmp_path
    )


# ---------------------------------------------------------------------------
# H2 — a failed ps probe must yield changed=UNKNOWN, not changed=True
# ---------------------------------------------------------------------------


def test_h2_start_changed_unknown_when_probe_fails(tmp_path: Path) -> None:
    # ps (running probe) fails -> _running_state is None -> start cannot claim
    # ownership (changed must be None, not True).
    runner = _ConfigurableDockerRunner(ps_running_rc=1)
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    result = driver.start(_workspace(tmp_path))
    assert result.state == RuntimeState.RUNNING
    assert result.changed is None, (
        "a failed running-probe must leave changed UNKNOWN, never True"
    )


def test_h2_start_changed_true_when_demonstrably_stopped(tmp_path: Path) -> None:
    # ps returns no running ids (rc 0) -> demonstrably not running -> changed True.
    runner = _ConfigurableDockerRunner(ps_running_rc=0, running_ids="")
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    result = driver.start(_workspace(tmp_path))
    assert result.changed is True


# ---------------------------------------------------------------------------
# H3 — cleanup must declare changed=True when stopped containers exist
# ---------------------------------------------------------------------------


def test_h3_cleanup_changed_when_only_stopped_containers_exist(tmp_path: Path) -> None:
    # No running containers, but `ps --all` reports resources -> down mutates.
    runner = _ConfigurableDockerRunner(running_ids="", all_ids="stopped123\n")
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    result = driver.cleanup(_workspace(tmp_path))
    assert result.changed is True, (
        "cleanup must observe ALL project resources (ps --all), not only running"
    )


def test_h3_cleanup_changed_false_when_no_resources(tmp_path: Path) -> None:
    runner = _ConfigurableDockerRunner(running_ids="", all_ids="")
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    result = driver.cleanup(_workspace(tmp_path))
    assert result.changed is False


# ---------------------------------------------------------------------------
# H4 — a runtime that mutates and then fails must be compensated on rollback
# ---------------------------------------------------------------------------


class _MutateThenFailRuntimeDriver:
    """start() mutates (marks running) then raises RuntimeStartFailedError
    declaring the partial mutation, so the transaction can compensate it."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.running = False

    @property
    def name(self) -> str:
        return "fake"

    def doctor(self, workspace):
        return ()

    def status(self, workspace):
        return RuntimeResult(
            RuntimeState.RUNNING if self.running else RuntimeState.STOPPED,
            "running" if self.running else "stopped",
        )

    def start(self, workspace):
        self._calls.append("start")
        self.running = True  # MUTATION happens...
        raise RuntimeStartFailedError(
            "mutated then failed",
            changed=True,
            resource_identity="runtime:fake",
            compensation_available=True,
        )

    def stop(self, workspace):
        self._calls.append("stop")
        self.running = False
        return RuntimeResult(RuntimeState.STOPPED, "stopped", changed=True)

    def cleanup(self, workspace):
        self._calls.append("cleanup")
        return RuntimeResult(RuntimeState.STOPPED, "down", changed=False)


def test_h4_runtime_mutate_then_fail_is_compensated(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _CONFIG_BODY + '\n[capabilities.runtime]\ndriver = "fake"\n',
    )
    from ramalio.core.startstop import StartWorkspaceService

    calls: list[str] = []
    driver = _MutateThenFailRuntimeDriver(calls)
    registry = CapabilityRegistry.with_capabilities(
        [RuntimeCapability(drivers={"fake": lambda _o, _c=None: driver})]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    # init: status is STOPPED so after_init runtime hooks are no-ops here
    # (runtime capability acts on after_start/before_stop/before_destroy).
    InitWorkspaceService(cfg, registry=registry).run("feat-r2h4")
    calls.clear()

    with pytest.raises(Exception):
        StartWorkspaceService(cfg, registry=registry).run("feat-r2h4")

    # The mutation (start) that failed must be compensated by a stop on rollback.
    assert calls == ["start", "stop"], (
        "a runtime that mutated before failing must be compensated (stop) on "
        f"rollback; calls={calls}"
    )
    assert driver.running is False


# ---------------------------------------------------------------------------
# H5 — zrok stop: UNKNOWN ownership preserves the record and fails closed
# ---------------------------------------------------------------------------


def test_h5_stop_unknown_ownership_preserves_record(tmp_path: Path, monkeypatch) -> None:
    import ramalio.capabilities.tunnels.zrok as zrok_mod
    from ramalio.capabilities.tunnels.base import TunnelWorkspace
    from ramalio.capabilities.tunnels.zrok import (
        TunnelRecord,
        TunnelStateStore,
        ZrokProvider,
    )
    from ramalio.core.errors import TunnelStopFailedError

    # PID reports alive, but its fingerprint cannot be read -> UNKNOWN.
    monkeypatch.setattr(zrok_mod, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(zrok_mod, "_read_start_time", lambda pid: None)

    store = TunnelStateStore(tmp_path, base=tmp_path / "state")
    store.save(
        TunnelRecord(target="feat-a", pid=4242, public_url="https://x", start_time="1")
    )
    provider = ZrokProvider(state_base=tmp_path / "state", stop_timeout=0.2)
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=tmp_path, identity=None, repository_root=tmp_path
    )

    with pytest.raises(TunnelStopFailedError):
        provider.stop(ws)

    # Evidence preserved: the record is NOT deleted on UNKNOWN.
    assert store.load("feat-a") is not None, (
        "UNKNOWN ownership must preserve the tunnel record, not delete it"
    )


def test_h5_status_unknown_ownership_is_degraded(tmp_path: Path, monkeypatch) -> None:
    import ramalio.capabilities.tunnels.zrok as zrok_mod
    from ramalio.capabilities.tunnels.base import TunnelState, TunnelWorkspace
    from ramalio.capabilities.tunnels.zrok import (
        TunnelRecord,
        TunnelStateStore,
        ZrokProvider,
    )

    monkeypatch.setattr(zrok_mod, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(zrok_mod, "_read_start_time", lambda pid: None)

    store = TunnelStateStore(tmp_path, base=tmp_path / "state")
    store.save(
        TunnelRecord(target="feat-a", pid=4242, public_url="https://x", start_time="1")
    )
    provider = ZrokProvider(state_base=tmp_path / "state")
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=tmp_path, identity=None, repository_root=tmp_path
    )
    result = provider.status(ws)
    assert result.state == TunnelState.DEGRADED


def test_h5_stop_not_owned_deletes_stale_record(tmp_path: Path, monkeypatch) -> None:
    import ramalio.capabilities.tunnels.zrok as zrok_mod
    from ramalio.capabilities.tunnels.base import TunnelState, TunnelWorkspace
    from ramalio.capabilities.tunnels.zrok import (
        TunnelRecord,
        TunnelStateStore,
        ZrokProvider,
    )

    # PID dead -> NOT_OWNED -> stale record safe to remove, no signal.
    monkeypatch.setattr(zrok_mod, "_pid_alive", lambda pid: False)

    store = TunnelStateStore(tmp_path, base=tmp_path / "state")
    store.save(
        TunnelRecord(target="feat-a", pid=4242, public_url="https://x", start_time="1")
    )
    provider = ZrokProvider(state_base=tmp_path / "state")
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=tmp_path, identity=None, repository_root=tmp_path
    )
    result = provider.stop(ws)
    assert result.state == TunnelState.STOPPED
    assert result.changed is False
    assert store.load("feat-a") is None


# ---------------------------------------------------------------------------
# H6 — doctor validates the compose file even without a target
# ---------------------------------------------------------------------------


def test_h6_doctor_validates_compose_file_without_target(tmp_path: Path) -> None:
    # No workspace (project-level doctor), but repository_root is known: the
    # compose-file existence check must still run.
    runner = _ConfigurableDockerRunner()
    driver = DockerComposeDriver(
        {"compose_file": "compose.yaml"},
        runner=runner,
        project_name="proj",
        repository_root=tmp_path,
    )
    # File absent -> check present and FAIL.
    checks = {c.check_id: c.ok for c in driver.doctor(None)}
    assert "DOCKER_COMPOSE_FILE" in checks, (
        "doctor must validate the compose file even without a target"
    )
    assert checks["DOCKER_COMPOSE_FILE"] is False

    # File present -> check passes.
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    checks2 = {c.check_id: c.ok for c in driver.doctor(None)}
    assert checks2["DOCKER_COMPOSE_FILE"] is True


# ---------------------------------------------------------------------------
# H7 — status maps DEGRADED / FAILED from per-service state
# ---------------------------------------------------------------------------


def _driver_with_ps_json(tmp_path: Path, services: list[dict]) -> DockerComposeDriver:
    payload = "\n".join(json.dumps(s) for s in services)
    runner = _ConfigurableDockerRunner(ps_json=payload)
    return DockerComposeDriver({}, runner=runner, project_name="proj")


def test_h7_status_degraded_on_mixed_services(tmp_path: Path) -> None:
    driver = _driver_with_ps_json(
        tmp_path,
        [
            {"Service": "web", "State": "running", "ExitCode": 0},
            {"Service": "worker", "State": "exited", "ExitCode": 1},
        ],
    )
    assert driver.status(_workspace(tmp_path)).state == RuntimeState.DEGRADED


def test_h7_status_failed_when_all_failed(tmp_path: Path) -> None:
    driver = _driver_with_ps_json(
        tmp_path,
        [
            {"Service": "web", "State": "exited", "ExitCode": 1},
            {"Service": "worker", "State": "exited", "ExitCode": 2},
        ],
    )
    assert driver.status(_workspace(tmp_path)).state == RuntimeState.FAILED


def test_h7_status_running_when_all_running(tmp_path: Path) -> None:
    driver = _driver_with_ps_json(
        tmp_path,
        [
            {"Service": "web", "State": "running", "ExitCode": 0},
            {"Service": "worker", "State": "running", "ExitCode": 0},
        ],
    )
    assert driver.status(_workspace(tmp_path)).state == RuntimeState.RUNNING


def test_h7_status_unknown_when_probe_unparsable(tmp_path: Path) -> None:
    runner = _ConfigurableDockerRunner(ps_json="not-json-at-all {{{")
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    assert driver.status(_workspace(tmp_path)).state == RuntimeState.UNKNOWN
