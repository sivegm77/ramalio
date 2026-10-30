"""Tests for the Docker Compose runtime driver (E6-S2) with a fake runner."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ramalio.capabilities.runtime.base import RuntimeState, RuntimeWorkspace
from ramalio.capabilities.runtime.docker_compose import (
    DockerComposeDriver,
    sanitize_project_name,
)
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.errors import RuntimeStartFailedError
from ramalio.core.target import Target


class FakeDockerRunner:
    """Records compose invocations and returns scripted results."""

    def __init__(self, *, available=True, compose=True, ps_running=False) -> None:
        self._available = available
        self._compose = compose
        self._ps_running = ps_running
        self.calls: list[tuple[str, ...]] = []
        self.extra_files_seen: list[tuple[str, ...]] = []
        self.fail_up = False

    @property
    def available(self) -> bool:
        return self._available

    def compose_available(self) -> bool:
        return self._available and self._compose

    def compose(self, project, compose_file, *args, cwd, env=None, extra_files=()):
        self.calls.append((project, compose_file, *args))
        self.extra_files_seen.append(extra_files)
        if args and args[0] == "up" and self.fail_up:
            return subprocess.CompletedProcess([], 1, "", "boom")
        if args and args[0] == "ps":
            # New status probe: `ps --all --format json` -> emit JSON.
            if "--format" in args and "json" in args:
                import json

                state = "running" if self._ps_running else "exited"
                exit_code = 0 if self._ps_running else 0
                obj = {"Service": "web", "State": state, "ExitCode": exit_code}
                return subprocess.CompletedProcess(
                    [], 0, json.dumps(obj) + "\n", ""
                )
            # Quiet probes (`--status=running --quiet`, `--all --quiet`).
            out = "abc123\n" if self._ps_running else ""
            return subprocess.CompletedProcess([], 0, out, "")
        return subprocess.CompletedProcess([], 0, "", "")


def _workspace(tmp_path: Path, target: str) -> RuntimeWorkspace:
    wt = tmp_path / target
    wt.mkdir(exist_ok=True)
    # A minimal fake identity is not needed for driver ops beyond target/path.
    from ramalio.core.naming import ResolvedWorkspaceIdentity
    from pathlib import PurePosixPath

    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted(target),
        branch_name=target,
        worktree_path=PurePosixPath(".local-wt") / target,
    )
    return RuntimeWorkspace(
        target=target, worktree_path=wt, identity=identity, repository_root=tmp_path
    )


# --- project naming (R3/AC-02) ---------------------------------------------


def test_sanitize_project_name() -> None:
    assert sanitize_project_name("SiVale-Feat/X") == "sivale-feat-x"
    assert sanitize_project_name("--__--") == "ramalio"


def test_ac02_project_name_differs_per_target(tmp_path: Path) -> None:
    driver = DockerComposeDriver({"project_pattern": "{project}-{target}"},
                                 runner=FakeDockerRunner(), project_name="proj")
    a = driver.project_name(_workspace(tmp_path, "alpha"))
    b = driver.project_name(_workspace(tmp_path, "bravo"))
    assert a == "proj-alpha"
    assert b == "proj-bravo"
    assert a != b


# --- start/stop/cleanup use -p and worktree cwd (R4/R5/R11) ----------------


def test_ac03_start_scoped_with_project(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    ws = _workspace(tmp_path, "alpha")
    result = driver.start(ws)
    assert result.state == RuntimeState.RUNNING
    # start() first probes running state (ps) then runs 'up'; both are scoped to
    # the alpha project. The 'up' invocation is the operation call.
    up_calls = [c for c in runner.calls if "up" in c]
    assert up_calls, "expected an 'up' invocation"
    assert up_calls[0][0] == "proj-alpha"
    # H3: the driver authoritatively reports it started the runtime (nothing
    # was running before this call).
    assert result.changed is True


def test_ac04_stop_scoped(tmp_path: Path) -> None:
    runner = FakeDockerRunner(ps_running=True)
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    driver.stop(_workspace(tmp_path, "alpha"))
    stop_calls = [c for c in runner.calls if "stop" in c]
    assert stop_calls, "expected a 'stop' invocation"
    assert stop_calls[0][0] == "proj-alpha"


def test_ac05_cleanup_no_volumes(tmp_path: Path) -> None:
    runner = FakeDockerRunner(ps_running=True)
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    driver.cleanup(_workspace(tmp_path, "alpha"))
    down_calls = [c for c in runner.calls if "down" in c]
    assert down_calls, "expected a 'down' invocation"
    call = down_calls[0]
    # AC-09: --volumes / -v never passed by default.
    assert "--volumes" not in call and "-v" not in call


# --- status mapping (R8/AC-06) ---------------------------------------------


def test_ac06_status_running(tmp_path: Path) -> None:
    driver = DockerComposeDriver(
        {}, runner=FakeDockerRunner(ps_running=True), project_name="proj"
    )
    assert driver.status(_workspace(tmp_path, "alpha")).state == RuntimeState.RUNNING


def test_ac06_status_stopped(tmp_path: Path) -> None:
    driver = DockerComposeDriver(
        {}, runner=FakeDockerRunner(ps_running=False), project_name="proj"
    )
    assert driver.status(_workspace(tmp_path, "alpha")).state == RuntimeState.STOPPED


# --- doctor (R2/AC-07) -----------------------------------------------------


def test_ac07_doctor_detects_missing_docker(tmp_path: Path) -> None:
    driver = DockerComposeDriver(
        {}, runner=FakeDockerRunner(available=False), project_name="proj"
    )
    checks = {c.check_id: c.ok for c in driver.doctor(None)}
    assert checks["DOCKER_AVAILABLE"] is False


# --- port injection (R9/AC-08) ---------------------------------------------


def test_ac08_port_injected_without_sivale_rule(tmp_path: Path) -> None:
    captured_env: dict[str, str] = {}

    class _EnvCapturingRunner(FakeDockerRunner):
        def compose(self, project, compose_file, *args, cwd, env=None, extra_files=()):
            if env:
                captured_env.update(env)
            return super().compose(project, compose_file, *args, cwd=cwd, env=env)

    runner = _EnvCapturingRunner()
    driver = DockerComposeDriver(
        {"port_env": "APP_PORT"},
        runner=runner,
        project_name="proj",
        port_provider=lambda ws: 8123,
    )
    driver.start(_workspace(tmp_path, "alpha"))
    assert captured_env.get("APP_PORT") == "8123"


# --- start failure maps to runtime error (R13) -----------------------------


def test_start_failure(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    runner.fail_up = True
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    with pytest.raises(RuntimeStartFailedError):
        driver.start(_workspace(tmp_path, "alpha"))


# --- driver registered & selectable (AC-01 negative: none still default) ---


def test_driver_registered_in_registry() -> None:
    from ramalio.capabilities.runtime.capability import _DRIVERS

    assert "docker-compose" in _DRIVERS
    assert "none" in _DRIVERS



# --- H5.B: optional compose_files override (E10-S1 §12) --------------------


def test_h5b_compose_files_absent_entry_silently_omitted(tmp_path: Path) -> None:
    """An entry that does not exist in the worktree is omitted, never fails
    (mirrors the legacy harness's optional docker-compose.override.yml)."""

    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"compose_files": ["docker-compose.override.yml"]},
        runner=runner,
        project_name="proj",
    )
    ws = _workspace(tmp_path, "alpha")
    # No override file created.
    result = driver.start(ws)
    assert result.state == RuntimeState.RUNNING
    up_seen = [
        ef for c, ef in zip(runner.calls, runner.extra_files_seen) if "up" in c
    ]
    assert up_seen
    assert up_seen[0] == ()


def test_h5b_compose_files_present_entry_added_as_extra_f(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"compose_files": ["docker-compose.override.yml"]},
        runner=runner,
        project_name="proj",
    )
    ws = _workspace(tmp_path, "alpha")
    (ws.worktree_path / "docker-compose.override.yml").write_text(
        "services: {}\n", encoding="utf-8"
    )
    driver.start(ws)
    up_seen = [
        ef for c, ef in zip(runner.calls, runner.extra_files_seen) if "up" in c
    ]
    assert up_seen
    assert up_seen[0] == ("docker-compose.override.yml",)


def test_h5b_compose_files_dotdot_rejected_at_config_time() -> None:
    """A '..' segment in compose_files is rejected as invalid config (string-
    level validation), never reaching a boundary check at runtime."""

    from ramalio.core.errors import CapabilityConfigInvalidError

    with pytest.raises(CapabilityConfigInvalidError):
        DockerComposeDriver(
            {"compose_files": ["../outside/evil.yml"]},
            runner=FakeDockerRunner(),
            project_name="proj",
        )


def test_h5b_compose_files_symlink_escape_rejected(tmp_path: Path) -> None:
    from ramalio.core.errors import CapabilityConfigInvalidError

    outside = tmp_path.parent / "outside-h5b-symlink"
    outside.mkdir(exist_ok=True)
    (outside / "evil.yml").write_text("services: {}\n", encoding="utf-8")

    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"compose_files": ["override.yml"]},
        runner=runner,
        project_name="proj",
    )
    ws = _workspace(tmp_path, "alpha")
    (ws.worktree_path / "override.yml").symlink_to(outside / "evil.yml")
    with pytest.raises(CapabilityConfigInvalidError):
        driver.start(ws)


def test_h5b_compose_files_absent_config_is_unchanged_default(tmp_path: Path) -> None:
    """AC-14: no compose_files declared -> identical behavior to pre-enmienda."""

    runner = FakeDockerRunner()
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    assert driver._config.compose_files == ()
    ws = _workspace(tmp_path, "alpha")
    driver.start(ws)
    up_seen = [
        ef for c, ef in zip(runner.calls, runner.extra_files_seen) if "up" in c
    ]
    assert up_seen
    assert up_seen[0] == ()


def test_h5b_unknown_option_still_rejected_with_compose_files_present() -> None:
    """Regression guard: compose_files being added to _KNOWN_OPTIONS must not
    accidentally widen the allowlist to accept anything else (H4)."""

    from ramalio.core.errors import CapabilityConfigInvalidError

    with pytest.raises(CapabilityConfigInvalidError):
        DockerComposeDriver(
            {"compose_files": ["x.yml"], "still_unknown": 1},
            runner=FakeDockerRunner(),
            project_name="proj",
        )
