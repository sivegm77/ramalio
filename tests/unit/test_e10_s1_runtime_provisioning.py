"""E10-S1 — runtime provisioning lifecycle tests.

Exercises the runtime extensions with a fake docker runner: the new
``provision`` operation, the ``RuntimeCommandExecutor`` seam (project vs.
workspace scopes, ``exec`` argv), env-file materialization, build/remove-volume
policies and the AFTER_INIT/AFTER_ADOPT wiring — all without a real Docker.

Covers AC-01..AC-13 of the spec.
"""

from __future__ import annotations

import subprocess
from pathlib import Path, PurePosixPath

import pytest

from ramalio.capabilities.runtime.base import (
    RuntimeCommandExecutor,
    RuntimeDriver,
    RuntimeExecRequest,
    RuntimeExecResult,
    RuntimeResult,
    RuntimeScope,
    RuntimeState,
    RuntimeWorkspace,
)
from ramalio.capabilities.runtime.docker_compose import DockerComposeDriver
from ramalio.capabilities.runtime.none_driver import NoneRuntimeDriver
from ramalio.core.errors import (
    CapabilityConfigInvalidError,
    RuntimeStartFailedError,
)
from ramalio.core.naming import ResolvedWorkspaceIdentity
from ramalio.core.target import Target


class FakeDockerRunner:
    """Records compose invocations and returns scripted results (bytes + text)."""

    def __init__(self, *, available=True, compose=True, ps_running=False) -> None:
        self._available = available
        self._compose = compose
        self._ps_running = ps_running
        self.calls: list[tuple[str, ...]] = []
        self.byte_calls: list[tuple[str, ...]] = []
        self.stdins: list[bytes | None] = []
        self.fail_up = False
        self.exec_stdout = b""
        self.exec_returncode = 0

    @property
    def available(self) -> bool:
        return self._available

    def compose_available(self) -> bool:
        return self._available and self._compose

    def compose(self, project, compose_file, *args, cwd, env=None, extra_files=()):
        self.calls.append((project, compose_file, *args))
        if args and args[0] == "up" and self.fail_up:
            return subprocess.CompletedProcess([], 1, "", "boom")
        if args and args[0] == "ps":
            if "--format" in args and "json" in args:
                import json

                state = "running" if self._ps_running else "exited"
                obj = {"Service": "web", "State": state, "ExitCode": 0}
                return subprocess.CompletedProcess([], 0, json.dumps(obj) + "\n", "")
            out = "abc123\n" if self._ps_running else ""
            return subprocess.CompletedProcess([], 0, out, "")
        return subprocess.CompletedProcess([], 0, "", "")

    def compose_bytes(self, project, compose_file, *args, cwd, env=None, stdin=None, extra_files=()):
        self.byte_calls.append((project, compose_file, *args))
        self.stdins.append(stdin)
        return subprocess.CompletedProcess(
            [], self.exec_returncode, self.exec_stdout, b""
        )


def _workspace(root: Path, target: str) -> RuntimeWorkspace:
    wt = root / ".local-wt" / target
    wt.mkdir(parents=True, exist_ok=True)
    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted(target),
        branch_name=target,
        worktree_path=PurePosixPath(".local-wt") / target,
    )
    return RuntimeWorkspace(
        target=target, worktree_path=wt, identity=identity, repository_root=root
    )


# --- AC-01: previous configs load with E10 defaults ------------------------


def test_ac01_previous_config_loads_with_safe_defaults(tmp_path: Path) -> None:
    driver = DockerComposeDriver(
        {"driver": "docker-compose", "compose_file": "compose.yaml"},
        runner=FakeDockerRunner(),
        project_name="proj",
    )
    # All new options default to the safe/backward-compatible values.
    assert driver.provision_on_init is False
    assert driver.provision_on_adopt is False
    assert driver._config.build_on_provision is False
    assert driver._config.base_project_pattern == "{project}"
    assert driver._config.materialize_env_file is None
    assert driver._config.remove_volumes_on_destroy is False


# --- AC-02: none driver provision is a no-op -------------------------------


def test_ac02_none_provision_is_noop(tmp_path: Path) -> None:
    result = NoneRuntimeDriver().provision(_workspace(tmp_path, "alpha"))
    assert result.state == RuntimeState.NOT_APPLICABLE
    # NoneRuntimeDriver is a RuntimeDriver but not a RuntimeCommandExecutor.
    assert isinstance(NoneRuntimeDriver(), RuntimeDriver)
    assert not isinstance(NoneRuntimeDriver(), RuntimeCommandExecutor)


# --- AC-05 / AC-06: build policy on provision vs. start --------------------


def test_ac06_provision_with_build_uses_up_build(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"build_on_provision": True}, runner=runner, project_name="proj"
    )
    driver.provision(_workspace(tmp_path, "alpha"))
    up_calls = [c for c in runner.calls if "up" in c]
    assert up_calls, "expected an 'up' invocation"
    assert "--build" in up_calls[0]
    # Scoped to the workspace project from the worktree cwd.
    assert up_calls[0][0] == "proj-alpha"


def test_ac06_provision_without_build_omits_build(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    driver.provision(_workspace(tmp_path, "alpha"))
    up_calls = [c for c in runner.calls if "up" in c]
    assert up_calls
    assert "--build" not in up_calls[0]


def test_ac05_normal_start_never_builds(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    # build_on_provision must not influence a normal start().
    driver = DockerComposeDriver(
        {"build_on_provision": True}, runner=runner, project_name="proj"
    )
    driver.start(_workspace(tmp_path, "alpha"))
    up_calls = [c for c in runner.calls if "up" in c]
    assert up_calls
    assert "--build" not in up_calls[0]


# --- AC-07: env file copied only when declared, never printed --------------


def test_ac07_env_file_copied_when_declared(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET_TOKEN=shh\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    dest = ws.worktree_path / ".env"
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == "SECRET_TOKEN=shh\n"


def test_ac07_env_file_absent_source_fails_before_start(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    with pytest.raises(RuntimeStartFailedError) as exc:
        driver.provision(_workspace(tmp_path, "alpha"))
    # Source content is never echoed; only the relative path is named.
    assert "shh" not in str(exc.value)
    # No compose command ran because materialization failed first.
    assert not any("up" in c for c in runner.calls)


def test_ac07_no_env_file_no_copy(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver({}, runner=runner, project_name="proj",
                                 repository_root=tmp_path)
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    assert not (ws.worktree_path / ".env").exists()


# --- AC-08: project vs. workspace scopes are distinct & deterministic ------


def test_ac08_scopes_derive_distinct_identities(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"project_pattern": "{project}-{target}", "base_project_pattern": "{project}"},
        runner=runner,
        project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")

    driver.ensure_service(RuntimeScope.WORKSPACE, ws, "db")
    driver.ensure_service(RuntimeScope.PROJECT, None, "db")

    ws_call = runner.calls[0]
    proj_call = runner.calls[1]
    assert ws_call[0] == "proj-alpha"   # workspace scope
    assert proj_call[0] == "proj"       # project scope (base pattern)
    assert ws_call[0] != proj_call[0]
    # Deterministic: same inputs -> same identity.
    assert driver.base_project_name() == "proj"
    assert driver.project_name(ws) == "proj-alpha"


# --- AC-09: command exec preserves argv and does not shell-tokenize --------


def test_ac09_exec_preserves_argv(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    runner.exec_stdout = b"appuser\n"
    driver = DockerComposeDriver({}, runner=runner, project_name="proj",
                                 repository_root=tmp_path)
    ws = _workspace(tmp_path, "alpha")
    request = RuntimeExecRequest(
        service="db",
        argv=("printenv", "POSTGRES USER WITH SPACES"),
        env={"PGOPTIONS": "-c x=1"},
        user="1000:1000",
        workdir="/var/www/html",
    )
    result = driver.exec(RuntimeScope.WORKSPACE, ws, request)

    assert isinstance(result, RuntimeExecResult)
    assert result.returncode == 0
    assert result.stdout == b"appuser\n"

    call = runner.byte_calls[0]
    # Exact argv, no shell tokenization: the argument with spaces stays a single
    # token; flags appear only when present.
    assert "exec" in call and "-T" in call
    assert "--user" in call and "1000:1000" in call
    assert "--workdir" in call and "/var/www/html" in call
    assert "-e" in call and "PGOPTIONS=-c x=1" in call
    assert "db" in call
    assert "POSTGRES USER WITH SPACES" in call


def test_ac09_exec_pipes_stdin(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver({}, runner=runner, project_name="proj",
                                 repository_root=tmp_path)
    ws = _workspace(tmp_path, "alpha")
    request = RuntimeExecRequest(
        service="db", argv=("psql",), stdin=b"SELECT 1;"
    )
    driver.exec(RuntimeScope.WORKSPACE, ws, request)
    assert runner.stdins[0] == b"SELECT 1;"


def test_ac09_exec_omits_absent_flags(tmp_path: Path) -> None:
    runner = FakeDockerRunner()
    driver = DockerComposeDriver({}, runner=runner, project_name="proj",
                                 repository_root=tmp_path)
    ws = _workspace(tmp_path, "alpha")
    driver.exec(RuntimeScope.WORKSPACE, ws, RuntimeExecRequest(
        service="db", argv=("true",)))
    call = runner.byte_calls[0]
    assert "--user" not in call
    assert "--workdir" not in call
    assert "-e" not in call


# --- AC-10: remove volumes is opt-in and target-scoped ---------------------


def test_ac10_remove_volumes_opt_in(tmp_path: Path) -> None:
    runner = FakeDockerRunner(ps_running=True)
    driver = DockerComposeDriver(
        {"remove_volumes_on_destroy": True}, runner=runner, project_name="proj"
    )
    driver.cleanup(_workspace(tmp_path, "alpha"))
    down_calls = [c for c in runner.calls if "down" in c]
    assert down_calls
    assert "-v" in down_calls[0]
    # Target-scoped project identity.
    assert down_calls[0][0] == "proj-alpha"


def test_ac10_remove_volumes_default_off(tmp_path: Path) -> None:
    runner = FakeDockerRunner(ps_running=True)
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    driver.cleanup(_workspace(tmp_path, "alpha"))
    down_calls = [c for c in runner.calls if "down" in c]
    assert down_calls
    assert "-v" not in down_calls[0] and "--volumes" not in down_calls[0]


# --- AC-12: no new drivers are added ---------------------------------------


def test_ac12_no_new_drivers(tmp_path: Path) -> None:
    from ramalio.capabilities.runtime.capability import _DRIVERS

    assert set(_DRIVERS) == {"none", "docker-compose"}


# --- config validation fail-closed -----------------------------------------


@pytest.mark.parametrize(
    "options",
    [
        {"provision_on_init": "yes"},
        {"provision_on_adopt": 1},
        {"build_on_provision": "true"},
        {"remove_volumes_on_destroy": "no"},
        {"base_project_pattern": ""},
        {"materialize_env_file": "/etc/passwd"},
        {"materialize_env_file": "../secret.env"},
        {"materialize_env_file": ""},
    ],
)
def test_invalid_options_fail_closed(options) -> None:
    with pytest.raises(CapabilityConfigInvalidError):
        DockerComposeDriver(options, runner=FakeDockerRunner(), project_name="proj")


def test_valid_relative_env_file_accepted() -> None:
    driver = DockerComposeDriver(
        {"materialize_env_file": "config/.env"},
        runner=FakeDockerRunner(),
        project_name="proj",
    )
    assert driver._config.materialize_env_file == "config/.env"



# --- AC-03/AC-04/AC-11: AFTER_INIT / AFTER_ADOPT wiring via the capability ---


class _RecordingDriver:
    """A fake RuntimeDriver that records which lifecycle ops were invoked.

    Lets the wiring be tested without Docker: it honors the provision flags and
    records provision/start/stop so tests can assert AFTER_INIT vs AFTER_ADOPT
    behavior and rollback compensation (stop of a runtime this call started).
    """

    def __init__(self, *, provision_on_init=False, provision_on_adopt=False) -> None:
        self.provision_on_init = provision_on_init
        self.provision_on_adopt = provision_on_adopt
        self.ops: list[str] = []
        self.fail_provision = False

    @property
    def name(self) -> str:
        return "recording"

    def doctor(self, workspace):
        return ()

    def status(self, workspace):
        # Report STOPPED so the capability's fail-closed heuristic attributes a
        # demonstrable start to this call (changed=True -> compensable).
        return RuntimeResult(RuntimeState.STOPPED, "stopped")

    def provision(self, workspace):
        self.ops.append("provision")
        if self.fail_provision:
            raise RuntimeStartFailedError("boom provision", changed=False)
        return RuntimeResult(RuntimeState.RUNNING, "provisioned", changed=True)

    def start(self, workspace):
        self.ops.append("start")
        return RuntimeResult(RuntimeState.RUNNING, "started", changed=True)

    def stop(self, workspace):
        self.ops.append("stop")
        return RuntimeResult(RuntimeState.STOPPED, "stopped", changed=True)

    def cleanup(self, workspace):
        self.ops.append("cleanup")
        return RuntimeResult(RuntimeState.STOPPED, "down", changed=True)


_RUNTIME_CONFIG = """
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

[capabilities.runtime]
driver = "recording"
"""


def _runtime_registry(driver):
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.capabilities.runtime.capability import RuntimeCapability

    cap = RuntimeCapability(drivers={"recording": lambda _o, _c=None: driver})
    return CapabilityRegistry.with_capabilities([cap])


@pytest.fixture
def runtime_project(git_repo_with_commit, write_config):
    write_config(git_repo_with_commit, _RUNTIME_CONFIG)
    return git_repo_with_commit


def test_ac03_provision_on_init_triggers_only_on_init(runtime_project, run_git):
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.init import InitWorkspaceService

    driver = _RecordingDriver(provision_on_init=True, provision_on_adopt=False)
    InitWorkspaceService(
        resolve_project_config(runtime_project),
        registry=_runtime_registry(driver),
    ).run("feat-init")
    assert "provision" in driver.ops


def test_ac04_provision_on_adopt_triggers_on_adopt(runtime_project, run_git):
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.adopt import AdoptWorkspaceService

    run_git(runtime_project, "branch", "feat-adopt", "main")
    driver = _RecordingDriver(provision_on_init=False, provision_on_adopt=True)
    AdoptWorkspaceService(
        resolve_project_config(runtime_project),
        registry=_runtime_registry(driver),
    ).run("feat-adopt")
    assert "provision" in driver.ops


def test_provision_on_init_false_skips_provision(runtime_project):
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.init import InitWorkspaceService

    driver = _RecordingDriver(provision_on_init=False)
    InitWorkspaceService(
        resolve_project_config(runtime_project),
        registry=_runtime_registry(driver),
    ).run("feat-noprov")
    assert "provision" not in driver.ops


def test_ac11_provision_failure_rolls_back_without_stopping_preexisting(
    runtime_project, run_git
):
    """A provision failure during init rolls back the worktree; because the
    failed provision reported changed=False (no demonstrable mutation), rollback
    does not stop a preexisting runtime (AC-11)."""
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.errors import CapabilityHookFailedError
    from ramalio.core.init import InitWorkspaceService
    from ramalio.git.repository import GitRepository

    driver = _RecordingDriver(provision_on_init=True)
    driver.fail_provision = True
    with pytest.raises(CapabilityHookFailedError):
        InitWorkspaceService(
            resolve_project_config(runtime_project),
            registry=_runtime_registry(driver),
        ).run("feat-fail")

    # The Git worktree/branch created by this init are rolled back.
    repo = GitRepository.from_root(runtime_project)
    assert not repo.branch_exists("feat-fail")
    # Provision failed with changed=False -> no compensating stop was needed.
    assert "stop" not in driver.ops



class _FailAfterProvision:
    """A second capability that fails after runtime provisioned successfully."""

    capability_name = "faulty"

    @property
    def name(self) -> str:
        return "faulty"

    def is_enabled(self, context) -> bool:
        return True

    def validate_config(self, context) -> None:
        return None

    def status(self, context):
        from ramalio.capabilities.base import CapabilityState, CapabilityStatus

        return CapabilityStatus("faulty", CapabilityState.READY, "ok")

    def doctor_checks(self, context):
        return ()

    def handle(self, event: str, context) -> object:
        if event == "after_init":
            raise RuntimeError("boom after provision")
        return None

    def compensate(self, event: str, context) -> None:
        return None


def test_ac11_successful_provision_is_compensated_by_stop(runtime_project):
    """When provision brought the runtime up (changed=True) and a later
    capability fails, rollback compensates by stopping the runtime this call
    started (E10-S1 R8.5/AC-11)."""
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.errors import CapabilityHookFailedError
    from ramalio.core.init import InitWorkspaceService

    driver = _RecordingDriver(provision_on_init=True)
    runtime_cap = RuntimeCapability(drivers={"recording": lambda _o, _c=None: driver})
    # runtime provisions first (registry order), then the faulty capability fails.
    registry = CapabilityRegistry.with_capabilities(
        [runtime_cap, _FailAfterProvision()]
    )
    # Enable the faulty capability in config too (fail-closed on unknown caps).
    cfg_path = runtime_project / ".ramalio.toml"
    cfg_path.write_text(
        _RUNTIME_CONFIG + "\n[capabilities.faulty]\nenabled = true\n",
        encoding="utf-8",
    )

    with pytest.raises(CapabilityHookFailedError):
        InitWorkspaceService(
            resolve_project_config(runtime_project),
            registry=registry,
        ).run("feat-comp-stop")

    # The runtime provisioned then was compensated with stop().
    assert driver.ops == ["provision", "stop"]



# ===========================================================================
# H3 — regression: materialize_env_file is safe, idempotent and ownership-
# aware (audit finding). Semantics:
#   destination symlink/outside worktree -> FAIL
#   destination exists and identical     -> no-op
#   destination exists and different     -> FAIL, preserve preexisting work
#   destination does not exist           -> create, own it, compensable
# ===========================================================================


def test_h3_destination_symlink_outside_worktree_rejected(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    ws.worktree_path.mkdir(parents=True, exist_ok=True)
    (ws.worktree_path / ".env").symlink_to(outside / "not-yet-existing")

    with pytest.raises(RuntimeStartFailedError):
        driver.provision(ws)
    assert not (outside / "not-yet-existing").exists()
    assert not any("up" in c for c in runner.calls)


def test_h3_destination_existing_identical_is_noop(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    (ws.worktree_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")

    driver.provision(ws)
    assert (ws.worktree_path / ".env").read_text(encoding="utf-8") == "SOURCE=1\n"
    # Compose still ran (idempotent re-provisioning).
    assert any("up" in c for c in runner.calls)


def test_h3_destination_existing_different_preserves_work(tmp_path: Path) -> None:
    """A preexisting, DIFFERENT .env (e.g. adopted worktree's own local
    config) must never be silently overwritten (E10-S4 R2)."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    (ws.worktree_path / ".env").write_text("LOCAL=keep\n", encoding="utf-8")

    with pytest.raises(RuntimeStartFailedError):
        driver.provision(ws)

    # Preexisting content is untouched; Compose never ran.
    assert (ws.worktree_path / ".env").read_text(encoding="utf-8") == "LOCAL=keep\n"
    assert not any("up" in c for c in runner.calls)


def test_h3_destination_missing_created_and_owned(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")

    driver.provision(ws)
    assert (ws.worktree_path / ".env").read_text(encoding="utf-8") == "SOURCE=1\n"
    # Ownership tracked (as an (st_dev, st_ino) identity) so compensation can
    # retire exactly this file.
    assert driver._materialized_by_call.get("alpha") is not None


def test_h3_compensation_retires_only_file_this_call_created(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")

    driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    driver.compensate_materialize_env_file(ws)
    assert not (ws.worktree_path / ".env").exists()
    assert driver._materialized_by_call.get("alpha") is None


def test_h3_compensation_never_removes_preexisting_file(tmp_path: Path) -> None:
    """compensate_materialize_env_file must be a no-op when the destination was
    NOT created by this call (idempotent no-op path)."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    (ws.worktree_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")

    driver.provision(ws)  # identical -> no-op, not owned by this call
    driver.compensate_materialize_env_file(ws)
    # The preexisting file survives compensation.
    assert (ws.worktree_path / ".env").read_text(encoding="utf-8") == "SOURCE=1\n"


def test_h3_failed_provision_after_materialize_is_compensable(tmp_path: Path) -> None:
    """If materialize succeeds but the subsequent `compose up` fails, the
    created file must be reported as a compensable mutation (never orphaned)."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    runner.fail_up = True
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")

    with pytest.raises(RuntimeStartFailedError) as exc:
        driver.provision(ws)

    # The file WAS created...
    assert (ws.worktree_path / ".env").exists()
    # ...and the failure declares a confirmed, compensable mutation so the
    # transaction never orphans it.
    assert exc.value.changed is True
    assert exc.value.compensation_available is True

    # Applying the driver's own compensation retires exactly that file.
    driver.compensate_materialize_env_file(ws)
    assert not (ws.worktree_path / ".env").exists()


def test_h3_adopt_with_own_env_is_never_overwritten_end_to_end(tmp_path: Path):
    """End-to-end via the capability wiring: after_adopt on a worktree that
    already has its own different .env must fail closed, not overwrite it."""

    from ramalio.capabilities import CapabilityRegistry
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.adopt import AdoptWorkspaceService
    from ramalio.core.errors import CapabilityHookFailedError

    root = tmp_path / "repo"
    root.mkdir()
    import subprocess

    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    import os

    for k, v in {
        "GIT_AUTHOR_NAME": "c", "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"], check=True, capture_output=True)
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True, capture_output=True)
    (root / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    (root / ".ramalio.toml").write_text(
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

[capabilities.runtime]
driver = "recording"
provision_on_adopt = true
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(root), "branch", "feat-env", "main"], check=True, capture_output=True)
    wt = root / ".local-wt" / "feat-env"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", str(wt), "feat-env"],
        check=True, capture_output=True,
    )
    (wt / ".env").write_text("LOCAL=keep\n", encoding="utf-8")

    class _RealMaterializeDriver(_RecordingDriver):
        """Wraps a real DockerComposeDriver just for _materialize_env_file."""

        def __init__(self, repository_root):
            super().__init__(provision_on_adopt=True)
            self._real = DockerComposeDriver(
                {"materialize_env_file": ".env"},
                runner=FakeDockerRunner(),
                project_name="proj",
                repository_root=repository_root,
            )

        def provision(self, workspace):
            self._real._materialize_env_file(workspace)
            return super().provision(workspace)

    driver = _RealMaterializeDriver(root)
    cap = RuntimeCapability(drivers={"recording": lambda _o, _c=None: driver})
    registry = CapabilityRegistry.with_capabilities([cap])

    with pytest.raises(CapabilityHookFailedError):
        AdoptWorkspaceService(
            resolve_project_config(root), registry=registry
        ).run("feat-env")

    # The adopted worktree's own .env survives untouched.
    assert (wt / ".env").read_text(encoding="utf-8") == "LOCAL=keep\n"



# ===========================================================================
# H4 — regression: [capabilities.runtime] fails closed on unknown keys
# (audit finding). Exercised through the real capability validation path
# (validate_config -> _driver -> DockerComposeDriver.__init__), the same path
# init/adopt/start/stop/destroy use before mutating anything.
# ===========================================================================


def test_h4_unknown_option_rejected_at_construction() -> None:
    with pytest.raises(CapabilityConfigInvalidError):
        DockerComposeDriver({"totally_unknown_option": 1}, runner=FakeDockerRunner())


def test_h4_unknown_option_rejected_via_capability_validate_config(
    tmp_path: Path,
) -> None:
    from ramalio.capabilities.base import CapabilityContext
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.config.loader import resolve_project_config

    import subprocess
    import os

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c", "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(tmp_path), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True, capture_output=True)
    (tmp_path / ".ramalio.toml").write_text(
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

[capabilities.runtime]
driver = "docker-compose"
totally_unknown_option = 1
""",
        encoding="utf-8",
    )
    config = resolve_project_config(tmp_path)
    cap = RuntimeCapability()
    ctx = CapabilityContext(config=config, identity=None)
    with pytest.raises(CapabilityConfigInvalidError):
        cap.validate_config(ctx)


def test_h4_init_blocked_by_unknown_runtime_option(tmp_path: Path) -> None:
    """End-to-end: init must fail closed (before any Git mutation) when
    [capabilities.runtime] declares an option the driver does not recognize."""

    from ramalio.config.loader import resolve_project_config
    from ramalio.core.errors import CapabilityConfigInvalidError as _CCIE
    from ramalio.core.init import InitWorkspaceService
    from ramalio.git.repository import GitRepository

    import subprocess
    import os

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c", "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(tmp_path), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True, capture_output=True)
    (tmp_path / ".ramalio.toml").write_text(
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

[capabilities.runtime]
driver = "docker-compose"
totally_unknown_option = 1
""",
        encoding="utf-8",
    )
    with pytest.raises(CapabilityConfigInvalidError):
        InitWorkspaceService(resolve_project_config(tmp_path)).run("feat-x")

    # Nothing was mutated: fail-closed happened before Git work.
    repo = GitRepository.from_root(tmp_path)
    assert not repo.branch_exists("feat-x")



# ===========================================================================
# F1 — regression: compensate_materialize_env_file must never swallow a
# compensation failure (audit finding post-H3 remediation).
# ===========================================================================


def test_f1_unlink_failure_propagates_not_swallowed(tmp_path: Path, monkeypatch) -> None:
    """A failed unlink() must propagate instead of being silently ignored;
    ownership must remain tracked (the resource is still owned/present)."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    def _boom(self):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", _boom)

    with pytest.raises(OSError):
        driver.compensate_materialize_env_file(ws)

    # Ownership must remain tracked: the file is still present and owned.
    assert driver._materialized_by_call.get("alpha") is not None


def test_f1_boundary_error_propagates_not_swallowed(tmp_path: Path) -> None:
    """A PathBoundaryError raised while re-resolving the destination during
    compensation must propagate, not be silently ignored."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    # Swap the destination for a symlink escaping the worktree AFTER creation,
    # simulating a boundary violation discovered during compensation.
    (ws.worktree_path / ".env").unlink()
    outside = tmp_path.parent / "f1-outside"
    outside.mkdir(exist_ok=True)
    (ws.worktree_path / ".env").symlink_to(outside / "evil")

    from ramalio.security import PathBoundaryError

    with pytest.raises(PathBoundaryError):
        driver.compensate_materialize_env_file(ws)

    # Ownership remains tracked because retirement was never confirmed.
    assert driver._materialized_by_call.get("alpha") is not None


def test_f1_capability_compensate_still_stops_runtime_when_env_compensation_fails(
    tmp_path: Path, monkeypatch
) -> None:
    """RuntimeCapability.compensate must still call driver.stop() even when
    compensate_materialize_env_file fails, then re-raise the original error
    so LifecycleTransaction records it as a rollback_error (never both
    compensations abandoned)."""

    from ramalio.capabilities.base import CapabilityContext
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.config.loader import resolve_project_config
    from ramalio.hooks import HookContext

    import subprocess
    import os

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c", "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(tmp_path), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True, capture_output=True)
    (tmp_path / ".ramalio.toml").write_text(
        """
[project]
name = "proj"
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

[capabilities.runtime]
driver = "recording"
provision_on_init = true
""",
        encoding="utf-8",
    )
    config = resolve_project_config(tmp_path)

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    real_driver = DockerComposeDriver(
        {"materialize_env_file": ".env", "provision_on_init": True},
        runner=runner,
        project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    real_driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    def _boom(self):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", _boom)

    cap = RuntimeCapability(drivers={"recording": lambda _o, _c=None: real_driver})
    cap_ctx = CapabilityContext(config=config, identity=ws.identity)
    hook_ctx = HookContext(capability_context=cap_ctx, operation="init")

    with pytest.raises(OSError):
        cap.compensate("after_init", hook_ctx)

    # driver.stop() still ran (recorded a 'stop' call) despite the env
    # compensation failure: neither compensation was abandoned.
    assert any("stop" in c for c in runner.calls)



# ===========================================================================
# F1-followup — regression: compensate_materialize_env_file must verify file
# IDENTITY (st_dev/st_ino) before unlinking, never trust a resolved path alone
# (audit finding: resolve_within_directory resolves symlinks, so a lexical
# path swapped for a symlink into another in-worktree file would otherwise
# resolve to — and delete — that unrelated file).
# ===========================================================================


def test_f1_followup_symlink_to_other_file_is_never_deleted(tmp_path: Path) -> None:
    """The owned .env is replaced by a symlink pointing at an unrelated,
    preexisting file inside the worktree. Compensation must refuse to touch
    it: neither the symlink nor the file it points to may be deleted."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    victim = ws.worktree_path / "victim.txt"
    victim.write_text("preexisting work that must survive\n", encoding="utf-8")
    (ws.worktree_path / ".env").unlink()
    (ws.worktree_path / ".env").symlink_to(victim)

    from ramalio.security import PathBoundaryError

    with pytest.raises(PathBoundaryError):
        driver.compensate_materialize_env_file(ws)

    # The victim file must survive untouched; the symlink is left in place
    # (rollback surfaces as parcial/unsafe rather than delete anything).
    assert victim.exists()
    assert victim.read_text(encoding="utf-8") == "preexisting work that must survive\n"
    # Ownership remains tracked: retirement was never confirmed.
    assert driver._materialized_by_call.get("alpha") is not None


def test_f1_followup_replaced_by_other_regular_file_is_never_deleted(
    tmp_path: Path,
) -> None:
    """The owned .env is replaced by a DIFFERENT regular file (different
    inode, no symlink involved). Compensation must detect the identity
    mismatch and refuse to delete it."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    (ws.worktree_path / ".env").unlink()
    (ws.worktree_path / ".env").write_text(
        "a completely different file now sits at this path\n", encoding="utf-8"
    )

    from ramalio.security import PathBoundaryError

    with pytest.raises(PathBoundaryError):
        driver.compensate_materialize_env_file(ws)

    assert (ws.worktree_path / ".env").exists()
    assert (ws.worktree_path / ".env").read_text(encoding="utf-8") == (
        "a completely different file now sits at this path\n"
    )
    assert driver._materialized_by_call.get("alpha") is not None


def test_f1_followup_matching_identity_still_deletes_normally(tmp_path: Path) -> None:
    """Regression guard: the identity check must not break the ordinary,
    unmodified case — the file this call created is still retired normally."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    driver.provision(ws)
    assert (ws.worktree_path / ".env").exists()

    driver.compensate_materialize_env_file(ws)

    assert not (ws.worktree_path / ".env").exists()
    assert driver._materialized_by_call.get("alpha") is None



# ===========================================================================
# F1.3 — regression: the ownership window between creating the destination and
# recording its identity must be exception-safe. A failure after the file may
# have been created must NEVER leave an orphaned, untracked .env: either the
# file this call created is retired, or the failure surfaces with the resource
# already retired (never success, never a silently orphaned mutation).
# (audit finding: _materialize_env_file created the file, then read_bytes/lstat
# could fail before ownership was recorded, leaving compensation unaware).
# ===========================================================================


def test_f1_3_capture_failure_after_create_leaves_no_orphaned_env(
    tmp_path: Path, monkeypatch
) -> None:
    """If capturing identity (lstat) fails after the file is created, the file
    this call created must be retired, not left orphaned, and the failure must
    surface as a RuntimeStartFailedError (never success)."""

    from ramalio.core.errors import RuntimeStartFailedError

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    dest = ws.worktree_path / ".env"

    original_lstat = Path.lstat

    def _boom_lstat(self):
        # Fail identity capture on the just-created destination only.
        if self == dest:
            raise OSError("simulated lstat failure after copy")
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", _boom_lstat)

    with pytest.raises(RuntimeStartFailedError):
        driver._materialize_env_file(ws)

    # No orphaned .env: the file this call created was retired on failure.
    assert not (ws.worktree_path / ".env").exists()
    # Ownership was never (incorrectly) recorded as a completed materialization.
    assert driver._materialized_by_call.get("alpha") is None


def test_f1_3_capture_failure_reports_no_mutation_when_file_retired(
    tmp_path: Path, monkeypatch
) -> None:
    """When identity capture fails but the created file IS successfully
    retired, the failure must be reported with changed=False (no compensation
    step needed) and never as success (INV-05)."""

    from ramalio.core.errors import PartialMutationError, RuntimeStartFailedError

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    dest = ws.worktree_path / ".env"

    original_lstat = Path.lstat

    def _boom_lstat(self):
        if self == dest:
            raise OSError("simulated lstat failure after copy")
        return original_lstat(self)

    monkeypatch.setattr(Path, "lstat", _boom_lstat)

    with pytest.raises(RuntimeStartFailedError) as excinfo:
        driver._materialize_env_file(ws)

    # File retired: reported as a non-mutating failure (no rollback step).
    assert isinstance(excinfo.value, PartialMutationError)
    assert excinfo.value.changed is False
    assert not dest.exists()
    assert driver._materialized_by_call.get("alpha") is None


def test_f1_3_preexisting_env_is_never_touched_on_create_failure(
    tmp_path: Path, monkeypatch
) -> None:
    """The cleanup on failure must only retire a file THIS call created. A
    preexisting, identical .env is a safe no-op (never reaches the create
    branch), so nothing is deleted even if a later step would fail."""

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    # Preexisting, identical .env in the worktree: materialize is a no-op and
    # never enters the create branch, so the cleanup path is not exercised.
    (ws.worktree_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")

    driver._materialize_env_file(ws)

    # Preexisting file survives untouched and is not tracked as owned.
    assert (ws.worktree_path / ".env").read_text(encoding="utf-8") == "SOURCE=1\n"
    assert driver._materialized_by_call.get("alpha") is None



# ===========================================================================
# F1.3 (follow-up) — regression: identity capture FAILS *and* the immediate
# cleanup unlink ALSO FAILS. The created .env must not become an orphaned,
# untracked mutation: the failure must declare a PartialMutationError
# (changed=True, compensation_available=True) so HookRunner records a
# transaction step and rollback drives the real compensation. Ownership is
# ALSO recorded degraded so the driver-level compensation can retire the file.
# (audit finding: a bare OSError was not recognized as a partial mutation, so
# the transaction never compensated the orphaned .env).
# ===========================================================================


def test_f1_3_identity_and_cleanup_both_fail_declare_partial_mutation(
    tmp_path: Path, monkeypatch
) -> None:
    """copy OK → identity capture FAIL → immediate unlink FAIL → the failure
    MUST be a PartialMutationError declaring changed=True and
    compensation_available=True, and ownership recorded degraded so the real
    compensation retires it."""

    import os as _os
    from ramalio.core.errors import PartialMutationError, RuntimeStartFailedError

    (tmp_path / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    dest = ws.worktree_path / ".env"

    original_lstat = Path.lstat

    def _boom_lstat(self):
        if self == dest:
            raise OSError("simulated identity lstat failure after copy")
        return original_lstat(self)

    def _boom_unlink(*_a, **_k):
        raise OSError("simulated cleanup unlink failure")

    monkeypatch.setattr(Path, "lstat", _boom_lstat)
    monkeypatch.setattr(_os, "unlink", _boom_unlink)

    with pytest.raises(RuntimeStartFailedError) as excinfo:
        driver._materialize_env_file(ws)

    # The mutation is declared to the transaction model (not a bare OSError).
    err = excinfo.value
    assert isinstance(err, PartialMutationError)
    assert err.changed is True
    assert err.compensation_available is True
    assert err.resource_identity == "materialize_env_file:alpha"

    # The file could not be cleaned up, so it is still present — the mutation
    # is NOT lost: ownership is recorded (degraded/unverified).
    assert dest.exists()
    tracked = driver._materialized_by_call.get("alpha")
    assert tracked is not None
    assert tracked.verified is False

    # A later compensation (cleanup no longer failing) retires the file that
    # this operation created, leaving nothing orphaned.
    monkeypatch.undo()
    driver.compensate_materialize_env_file(ws)
    assert not dest.exists()
    assert driver._materialized_by_call.get("alpha") is None


def test_f1_3_degraded_ownership_compensation_failure_propagates(
    tmp_path: Path, monkeypatch
) -> None:
    """A degraded (unverified) ownership entry whose retirement fails must
    surface the mutation as an inconsistency (error propagates) and keep the
    ownership tracked — never silently forgotten."""

    from ramalio.capabilities.runtime.docker_compose import _EnvFileIdentity

    runner = FakeDockerRunner()
    driver = DockerComposeDriver(
        {"materialize_env_file": ".env"}, runner=runner, project_name="proj",
        repository_root=tmp_path,
    )
    ws = _workspace(tmp_path, "alpha")
    dest = ws.worktree_path / ".env"
    dest.write_text("created-but-unwitnessed\n", encoding="utf-8")
    driver._materialized_by_call["alpha"] = _EnvFileIdentity.unverified()

    def _boom_unlink(self, *_a, **_k):
        raise OSError("simulated retirement failure")

    monkeypatch.setattr(Path, "unlink", _boom_unlink)

    with pytest.raises(OSError):
        driver.compensate_materialize_env_file(ws)

    # Mutation surfaced as inconsistency; ownership remains tracked.
    assert driver._materialized_by_call.get("alpha") is not None



# ===========================================================================
# F1.3 (lifecycle integration) — the decisive regression: a real `adopt` over
# a PREEXISTING worktree whose after_adopt provisioning creates a .env and
# then fails to record its identity AND fails the immediate cleanup, must have
# that .env compensated by the REAL rollback path (HookRunner ->
# LifecycleTransaction -> RuntimeCapability.compensate ->
# compensate_materialize_env_file). Nobody calls the driver compensation by
# hand: the transaction must drive it because the failure declares a
# PartialMutationError. The preexisting worktree/Git must be preserved.
# ===========================================================================


def test_f1_3_adopt_rollback_compensates_orphaned_env_end_to_end(
    tmp_path: Path, monkeypatch
) -> None:
    import os
    import subprocess

    from ramalio.capabilities import CapabilityRegistry
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.adopt import AdoptWorkspaceService
    from ramalio.core.errors import CapabilityHookFailedError

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c", "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "seed"], check=True, capture_output=True)
    # Source .env at the repository root that provisioning copies into worktree.
    (root / ".env").write_text("SOURCE=1\n", encoding="utf-8")
    (root / ".ramalio.toml").write_text(
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

[capabilities.runtime]
driver = "recording"
provision_on_adopt = true
""",
        encoding="utf-8",
    )
    # PREEXISTING worktree adopted by this operation (existing-worktree scenario):
    # it has NO .env of its own, so any .env present after rollback would be an
    # orphan created by the failed provisioning.
    subprocess.run(["git", "-C", str(root), "branch", "feat-env", "main"], check=True, capture_output=True)
    wt = root / ".local-wt" / "feat-env"
    subprocess.run(
        ["git", "-C", str(root), "worktree", "add", str(wt), "feat-env"],
        check=True, capture_output=True,
    )
    assert not (wt / ".env").exists()

    dest_env = wt / ".env"
    original_lstat = Path.lstat
    original_os_unlink = os.unlink
    # Phase control: identity-capture failure must happen ONLY during
    # provisioning. Once provisioning has raised, the transactional rollback
    # runs the real compensation, which must be allowed to lstat/unlink
    # normally to actually retire the orphaned .env.
    state = {"provisioning": True}

    def _boom_lstat(self):
        if state["provisioning"] and self == dest_env:
            raise OSError("simulated identity capture failure after copy")
        return original_lstat(self)

    def _boom_os_unlink(path, *a, **k):
        # Fail ONLY the immediate best-effort cleanup inside _materialize_env_file
        # (which uses os.unlink) during provisioning, so a degraded-ownership
        # PartialMutationError is raised and the .env is left for the
        # transactional rollback to retire.
        if state["provisioning"] and str(path) == str(dest_env):
            raise OSError("simulated immediate cleanup failure")
        return original_os_unlink(path, *a, **k)

    monkeypatch.setattr(Path, "lstat", _boom_lstat)
    monkeypatch.setattr(os, "unlink", _boom_os_unlink)

    class _RealMaterializeDriver(_RecordingDriver):
        def __init__(self, repository_root):
            super().__init__(provision_on_adopt=True)
            self._real = DockerComposeDriver(
                {"materialize_env_file": ".env"},
                runner=FakeDockerRunner(),
                project_name="proj",
                repository_root=repository_root,
            )

        def provision(self, workspace):
            # Materialize creates the .env, then identity capture fails and the
            # immediate cleanup fails too: raises a PartialMutationError.
            try:
                self._real._materialize_env_file(workspace)
            finally:
                # From now on (rollback), stop simulating filesystem failures so
                # the REAL transaction-driven compensation can retire the .env.
                state["provisioning"] = False
            return super().provision(workspace)

        def compensate_materialize_env_file(self, workspace):
            # The transaction-driven rollback reaches HERE (not a manual call).
            return self._real.compensate_materialize_env_file(workspace)

    driver = _RealMaterializeDriver(root)
    cap = RuntimeCapability(drivers={"recording": lambda _o, _c=None: driver})
    registry = CapabilityRegistry.with_capabilities([cap])

    # adopt must fail...
    with pytest.raises(CapabilityHookFailedError):
        AdoptWorkspaceService(
            resolve_project_config(root), registry=registry
        ).run("feat-env")

    # ...and the rollback must have retired the orphaned .env WITHOUT anyone
    # calling the driver compensation by hand. The preexisting worktree/Git are
    # preserved (the worktree dir and its seeded files remain).
    assert not dest_env.exists(), "rollback must compensate the orphaned .env"
    assert wt.exists()
    assert (wt / "README.md").read_text(encoding="utf-8") == "seed\n"
