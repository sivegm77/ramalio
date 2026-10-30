"""E10-S2 — bootstrap Composer + readiness tests.

Covers config validation (fail-closed), the host and runtime executors, the
writable probe, artifact readiness, the AFTER_INIT/AFTER_ADOPT wiring, secret
redaction and status/doctor — all without a real Composer or Docker.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

import pytest

from ramalio.capabilities.base import CapabilityContext, CapabilityState
from ramalio.capabilities.bootstrap import BootstrapCapability
from ramalio.capabilities.bootstrap.composer import ComposerProvider
from ramalio.capabilities.bootstrap.models import (
    ArtifactKind,
    parse_bootstrap_config,
)
from ramalio.capabilities.runtime.base import (
    RuntimeExecResult,
    RuntimeResult,
    RuntimeScope,
    RuntimeState,
)
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    BootstrapProviderFailedError,
    BootstrapReadinessFailedError,
    CapabilityConfigInvalidError,
    CapabilityHookFailedError,
)
from ramalio.core.naming import ResolvedWorkspaceIdentity
from ramalio.core.target import Target


# --- config parsing / validation (AC-02, AC-09) ----------------------------


def test_absent_section_is_disabled() -> None:
    config = parse_bootstrap_config({})
    assert config.enabled is False


def test_valid_host_config() -> None:
    config = parse_bootstrap_config(
        {
            "enabled": True,
            "provider": "composer",
            "executor": "host",
            "arguments": ["install", "--no-dev"],
            "writable_paths": ["storage"],
        }
    )
    assert config.enabled is True
    assert config.provider == "composer"
    assert config.executor == "host"
    assert config.arguments == ("install", "--no-dev")
    assert config.writable_paths == ("storage",)


def test_default_arguments_are_composer_install() -> None:
    config = parse_bootstrap_config({"enabled": True, "provider": "composer"})
    assert config.arguments == (
        "install",
        "--no-interaction",
        "--prefer-dist",
        "--no-progress",
    )
    assert config.on_init is True
    assert config.on_adopt is True
    assert config.executor == "host"


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": True, "provider": "npm"},              # AC-09 only composer
        {"enabled": True, "provider": "composer", "executor": "docker"},
        {"enabled": True, "unknown_key": 1},               # unknown key
        {"enabled": True, "driver": "x"},                  # driver not valid
        {"enabled": True, "arguments": "install"},         # not an array
        {"enabled": True, "arguments": []},                # empty argv
        {"enabled": True, "pass_env": ["A=1"]},            # inline value
        {"enabled": True, "writable_paths": ["/abs"]},     # absolute
        {"enabled": True, "writable_paths": ["../x"]},     # traversal
        {"enabled": True, "artifacts": [{"path": "x", "kind": "socket"}]},
        {"enabled": True, "executor": "host", "runtime_service": "app"},  # host+runtime_*
        {"enabled": True, "executor": "runtime"},          # missing runtime_*
        {"enabled": True, "executor": "runtime", "runtime_service": "app",
         "runtime_workdir": "/w", "runtime_user": "root"},  # bad user alias
    ],
)
def test_invalid_config_fails_closed(options) -> None:
    with pytest.raises(CapabilityConfigInvalidError):
        parse_bootstrap_config(options)


def test_enabled_requires_provider() -> None:
    with pytest.raises(CapabilityConfigInvalidError):
        parse_bootstrap_config({"enabled": True})


def test_runtime_config_valid() -> None:
    config = parse_bootstrap_config(
        {
            "enabled": True,
            "provider": "composer",
            "executor": "runtime",
            "runtime_service": "app",
            "runtime_workdir": "/var/www/html",
            "runtime_user": "host",
            "writable_paths": ["storage", "bootstrap/cache"],
            "artifacts": [{"path": "vendor/autoload.php", "kind": "file"}],
        }
    )
    assert config.executor == "runtime"
    assert config.runtime_service == "app"
    assert config.runtime_user == "host"
    assert config.artifacts[0].kind is ArtifactKind.FILE


# --- host executor (AC-03, AC-05, AC-06) -----------------------------------


class _FakeRunner:
    """Records the CommandSpec passed to run()."""

    def __init__(self, *, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr
        self.specs: list = []

    def run(self, spec, *, capture: bool = True):
        self.specs.append(spec)
        return subprocess.CompletedProcess(list(spec.argv), self.returncode, "", self.stderr)


def _host_config(**over):
    base = {
        "enabled": True,
        "provider": "composer",
        "executor": "host",
        "arguments": ["install", "--no-interaction"],
    }
    base.update(over)
    return parse_bootstrap_config(base)


def test_ac03_host_uses_exact_argv_and_cwd(tmp_path: Path) -> None:
    runner = _FakeRunner()
    config = _host_config()
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    provider.provision()
    spec = runner.specs[0]
    assert spec.argv == ("composer", "install", "--no-interaction")
    assert spec.cwd == tmp_path


def test_ac03_host_env_is_explicit_and_safe(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MY_TOKEN", "supersecret")
    runner = _FakeRunner()
    config = _host_config(
        environment={"COMPOSER_HOME": "/tmp/composer"},
        pass_env=["MY_TOKEN"],
    )
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    provider.provision()
    env = runner.specs[0].env
    assert env["COMPOSER_HOME"] == "/tmp/composer"
    # pass_env forwards the allowlisted name explicitly.
    assert env["MY_TOKEN"] == "supersecret"


def test_ac05_writable_probe_host(tmp_path: Path) -> None:
    runner = _FakeRunner()
    config = _host_config(writable_paths=["storage"])
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    provider.provision()
    # The probe created (and cleaned) the directory; Composer then ran.
    assert (tmp_path / "storage").is_dir()
    assert not (tmp_path / "storage" / ".ramalio-writable-probe").exists()
    assert runner.specs, "composer should have run after a successful probe"


def test_ac06_artifacts_validated(tmp_path: Path) -> None:
    runner = _FakeRunner()
    config = _host_config(artifacts=[{"path": "vendor/autoload.php", "kind": "file"}])
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    # Composer "ran" but produced no artifact -> readiness fails.
    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()
    # Now create the artifact and it passes.
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "autoload.php").write_text("<?php", encoding="utf-8")
    provider.provision()


def test_ac06_executable_artifact(tmp_path: Path) -> None:
    runner = _FakeRunner()
    config = _host_config(artifacts=[{"path": "bin/tool", "kind": "executable"}])
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    (tmp_path / "bin").mkdir()
    tool = tmp_path / "bin" / "tool"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    # Not executable yet -> fails.
    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()
    tool.chmod(0o755)
    provider.provision()


def test_composer_failure_is_provider_error(tmp_path: Path) -> None:
    runner = _FakeRunner(returncode=1, stderr="boom")
    config = _host_config()
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    with pytest.raises(BootstrapProviderFailedError):
        provider.provision()


def test_ac08_secrets_not_in_provider_error(tmp_path: Path) -> None:
    runner = _FakeRunner(returncode=1, stderr="AUTH_TOKEN=deadbeef bad credentials")
    config = _host_config()
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    with pytest.raises(BootstrapProviderFailedError) as exc:
        provider.provision()
    assert "deadbeef" not in str(exc.value)


def test_probe_failure_is_readiness_not_composer(tmp_path: Path) -> None:
    # Make the writable path a FILE so mkdir fails -> readiness failure.
    (tmp_path / "storage").write_text("x", encoding="utf-8")
    runner = _FakeRunner()
    config = _host_config(writable_paths=["storage"])
    provider = ComposerProvider(config, worktree_path=tmp_path, runner=runner)
    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()
    # Composer never ran because the probe failed first (R6).
    assert not runner.specs


# --- runtime executor (AC-04) ----------------------------------------------


class _FakeExecutor:
    """A RuntimeCommandExecutor spy that records exec requests."""

    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode = returncode
        self.requests: list = []
        self.scopes: list = []

    def ensure_service(self, scope, workspace, service):
        return RuntimeResult(RuntimeState.RUNNING, "up")

    def exec(self, scope, workspace, request) -> RuntimeExecResult:
        self.requests.append(request)
        self.scopes.append(scope)
        return RuntimeExecResult(self.returncode, b"", b"")


def test_ac04_runtime_uses_executor_not_docker(tmp_path: Path) -> None:
    executor = _FakeExecutor()
    config = parse_bootstrap_config(
        {
            "enabled": True,
            "provider": "composer",
            "executor": "runtime",
            "runtime_service": "app",
            "runtime_workdir": "/var/www/html",
            "runtime_user": "host",
            "writable_paths": ["storage"],
        }
    )
    provider = ComposerProvider(config, worktree_path=tmp_path)
    provider.provision(
        executor=executor, scope=RuntimeScope.WORKSPACE, workspace=None
    )
    # The writable probe and composer both went through the executor.
    assert executor.requests, "expected exec requests via the runtime executor"
    composer_reqs = [r for r in executor.requests if r.argv[0] == "composer"]
    assert composer_reqs
    req = composer_reqs[0]
    assert req.service == "app"
    assert req.workdir == "/var/www/html"
    # runtime_user='host' resolves to a concrete uid:gid.
    assert req.user == f"{os.getuid()}:{os.getgid()}"
    # The probe used two structured requests (touch/rm), never a shell.
    probe_reqs = [r for r in executor.requests if r.argv[0] in ("touch", "rm")]
    assert probe_reqs and probe_reqs[0].argv[0] == "touch"
    assert not any(r.argv[0] == "sh" for r in executor.requests)


# --- capability wiring (AC-07, AC-10) --------------------------------------


_BOOTSTRAP_CONFIG = """
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

[capabilities.bootstrap]
enabled = true
provider = "composer"
executor = "host"
arguments = ["install"]
"""


@pytest.fixture
def bootstrap_project(git_repo_with_commit, write_config):
    write_config(git_repo_with_commit, _BOOTSTRAP_CONFIG)
    return git_repo_with_commit


def _ctx(project, target: str | None = None) -> CapabilityContext:
    config = resolve_project_config(project)
    identity = None
    if target is not None:
        identity = ResolvedWorkspaceIdentity(
            target=Target.from_trusted(target),
            branch_name=target,
            worktree_path=PurePosixPath(".local-wt") / target,
        )
    return CapabilityContext(config=config, identity=identity)


def test_ac01_project_without_bootstrap_unchanged(git_repo_with_commit, write_config):
    write_config(
        git_repo_with_commit,
        _BOOTSTRAP_CONFIG.split("[capabilities.bootstrap]")[0],
    )
    cap = BootstrapCapability()
    ctx = _ctx(git_repo_with_commit)
    assert cap.is_enabled(ctx) is False
    assert cap.status(ctx).state == CapabilityState.DISABLED


def test_ac10_status_disabled_and_ready(bootstrap_project):
    cap = BootstrapCapability()
    # No target -> READY when config valid.
    assert cap.status(_ctx(bootstrap_project)).state == CapabilityState.READY


def test_ac10_status_degraded_when_artifacts_missing(bootstrap_project, write_config):
    write_config(
        bootstrap_project,
        _BOOTSTRAP_CONFIG
        + '\n[[capabilities.bootstrap.artifacts]]\npath = "vendor/autoload.php"\nkind = "file"\n',
    )
    cap = BootstrapCapability()
    ctx = _ctx(bootstrap_project, "feat-x")
    assert cap.status(ctx).state == CapabilityState.DEGRADED


def test_ac07_adopt_runs_bootstrap(bootstrap_project, run_git, monkeypatch):
    """adopt executes bootstrap when enabled (AC-07)."""
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.core.adopt import AdoptWorkspaceService

    run_git(bootstrap_project, "branch", "feat-adopt", "main")

    calls: list = []

    class _SpyProvider(ComposerProvider):
        def provision(self, *, executor=None, scope=None, workspace=None):
            calls.append("provision")

    # Patch the provider registry to a spy.
    import ramalio.capabilities.bootstrap.capability as capmod

    monkeypatch.setitem(capmod._PROVIDERS, "composer", _SpyProvider)
    registry = CapabilityRegistry.with_capabilities([BootstrapCapability()])
    AdoptWorkspaceService(
        resolve_project_config(bootstrap_project), registry=registry
    ).run("feat-adopt")
    assert calls == ["provision"]


def test_init_runs_bootstrap(bootstrap_project, monkeypatch):
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.core.init import InitWorkspaceService

    calls: list = []

    class _SpyProvider(ComposerProvider):
        def provision(self, *, executor=None, scope=None, workspace=None):
            calls.append("provision")

    import ramalio.capabilities.bootstrap.capability as capmod

    monkeypatch.setitem(capmod._PROVIDERS, "composer", _SpyProvider)
    registry = CapabilityRegistry.with_capabilities([BootstrapCapability()])
    InitWorkspaceService(
        resolve_project_config(bootstrap_project), registry=registry
    ).run("feat-init")
    assert calls == ["provision"]


def test_bootstrap_failure_fails_init(bootstrap_project, monkeypatch):
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.core.init import InitWorkspaceService
    from ramalio.git.repository import GitRepository

    class _FailingProvider(ComposerProvider):
        def provision(self, *, executor=None, scope=None, workspace=None):
            raise BootstrapReadinessFailedError("missing artifact")

    import ramalio.capabilities.bootstrap.capability as capmod

    monkeypatch.setitem(capmod._PROVIDERS, "composer", _FailingProvider)
    registry = CapabilityRegistry.with_capabilities([BootstrapCapability()])
    with pytest.raises(CapabilityHookFailedError):
        InitWorkspaceService(
            resolve_project_config(bootstrap_project), registry=registry
        ).run("feat-fail")

    # The workspace init is rolled back (bootstrap failed after worktree).
    repo = GitRepository.from_root(bootstrap_project)
    assert not repo.branch_exists("feat-fail")


def test_ac09_registered_once_no_dynamic_discovery():
    import ramalio.capabilities.bootstrap.capability as capmod

    assert set(capmod._PROVIDERS) == {"composer"}


def test_runtime_executor_required_fails_config(git_repo_with_commit, write_config):
    """executor='runtime' without a runtime that supports exec fails config."""
    write_config(
        git_repo_with_commit,
        _BOOTSTRAP_CONFIG.replace('executor = "host"', 'executor = "runtime"')
        .replace('arguments = ["install"]',
                 'arguments = ["install"]\nruntime_service = "app"\n'
                 'runtime_workdir = "/w"\nruntime_user = "host"'),
    )
    cap = BootstrapCapability()
    with pytest.raises(CapabilityConfigInvalidError):
        cap.validate_config(_ctx(git_repo_with_commit, "feat-x"))



def test_composer_partial_mutation_is_not_faked_rollback(bootstrap_project, monkeypatch):
    """A Composer failure that may have mutated is recorded as NOT_SAFE, so the
    transaction never fakes a complete rollback of dependencies (§6)."""
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.core.errors import LifecycleRollbackIncompleteError
    from ramalio.core.init import InitWorkspaceService
    from ramalio.git.repository import GitRepository

    class _MutatingFailingProvider(ComposerProvider):
        def provision(self, *, executor=None, scope=None, workspace=None):
            # UNKNOWN mutation (changed=None) -> transaction must classify the
            # step NOT_SAFE rather than assume zero mutation.
            raise BootstrapProviderFailedError(
                "composer install failed midway",
                changed=None,
                resource_identity="composer",
                compensation_available=False,
            )

    import ramalio.capabilities.bootstrap.capability as capmod

    monkeypatch.setitem(capmod._PROVIDERS, "composer", _MutatingFailingProvider)
    registry = CapabilityRegistry.with_capabilities([BootstrapCapability()])

    # The unsafe (non-compensable) mutation surfaces a rollback-incomplete
    # error instead of a clean success or a faked rollback.
    with pytest.raises(LifecycleRollbackIncompleteError):
        InitWorkspaceService(
            resolve_project_config(bootstrap_project), registry=registry
        ).run("feat-partial")

    # Git worktree/branch are still retired (they are separately owned + safe),
    # but the composer mutation was surfaced as not-safe.
    repo = GitRepository.from_root(bootstrap_project)
    assert not repo.branch_exists("feat-partial")



# ===========================================================================
# H1 — regression: writable probe never reaches a shell (audit finding)
# ===========================================================================


@pytest.mark.parametrize(
    "malicious_rel",
    [
        "storage;echo INJECTED",
        "storage$(echo INJECTED)",
        "storage`echo INJECTED`",
        "storage && echo INJECTED",
        "storage with spaces",
    ],
)
def test_h1_probe_runtime_never_shell_tokenizes(tmp_path: Path, malicious_rel: str) -> None:
    """Shell metacharacters in ``writable_paths`` must stay literal text inside
    a single argv element; the probe must never be executed via ``sh -c``."""

    executor = _FakeExecutor()
    config = parse_bootstrap_config(
        {
            "enabled": True,
            "provider": "composer",
            "executor": "runtime",
            "runtime_service": "app",
            "runtime_workdir": "/var/www/html",
            "runtime_user": "host",
            "writable_paths": [malicious_rel],
        }
    )
    provider = ComposerProvider(config, worktree_path=tmp_path)
    provider.provision(executor=executor, scope=RuntimeScope.WORKSPACE, workspace=None)

    # No request ever invokes a shell.
    assert not any(r.argv[0] in ("sh", "bash", "/bin/sh") for r in executor.requests)
    # The marker (derived from the malicious rel) is passed as ONE argv
    # element to touch/rm, never split or interpreted.
    touch_reqs = [r for r in executor.requests if r.argv[0] == "touch"]
    assert touch_reqs
    assert len(touch_reqs[0].argv) == 3  # ("touch", "--", marker)
    assert touch_reqs[0].argv[1] == "--"
    assert malicious_rel.rstrip("/") in touch_reqs[0].argv[2]
    rm_reqs = [r for r in executor.requests if r.argv[0] == "rm"]
    assert rm_reqs
    assert len(rm_reqs[0].argv) == 3
    assert rm_reqs[0].argv[1] == "--"


# ===========================================================================
# H2 — regression: bootstrap cannot escape the worktree via symlink
# ===========================================================================


def test_h2_writable_symlink_outside_worktree_rejected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (worktree / "link").symlink_to(outside, target_is_directory=True)

    runner = _FakeRunner()
    config = _host_config(writable_paths=["link"])
    provider = ComposerProvider(config, worktree_path=worktree, runner=runner)

    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()
    # Nothing was written inside the externally-linked directory.
    assert not (outside / ".ramalio-writable-probe").exists()
    # Composer never ran because the probe was rejected before mutating.
    assert not runner.specs


def test_h2_writable_nested_symlink_outside_worktree_rejected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    (worktree / "storage").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (worktree / "storage" / "cache").symlink_to(outside, target_is_directory=True)

    runner = _FakeRunner()
    config = _host_config(writable_paths=["storage/cache"])
    provider = ComposerProvider(config, worktree_path=worktree, runner=runner)

    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()
    assert not (outside / ".ramalio-writable-probe").exists()


def test_h2_artifact_symlink_outside_worktree_rejected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside_file = tmp_path / "outside.php"
    outside_file.write_text("<?php", encoding="utf-8")
    (worktree / "vendor").mkdir()
    (worktree / "vendor" / "autoload.php").symlink_to(outside_file)

    runner = _FakeRunner()
    config = _host_config(
        artifacts=[{"path": "vendor/autoload.php", "kind": "file"}]
    )
    provider = ComposerProvider(config, worktree_path=worktree, runner=runner)

    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()


def test_h2_artifact_nested_symlink_outside_worktree_rejected(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "bin").mkdir()
    tool = outside / "bin" / "pest"
    tool.write_text("#!/bin/sh\n", encoding="utf-8")
    tool.chmod(0o755)
    (worktree).mkdir()
    (worktree / "vendor").symlink_to(outside, target_is_directory=True)

    runner = _FakeRunner()
    config = _host_config(
        artifacts=[{"path": "vendor/bin/pest", "kind": "executable"}]
    )
    provider = ComposerProvider(config, worktree_path=worktree, runner=runner)

    with pytest.raises(BootstrapReadinessFailedError):
        provider.provision()


def test_h2_readiness_ok_false_on_symlink_escape(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    outside_file = tmp_path / "outside.php"
    outside_file.write_text("<?php", encoding="utf-8")
    (worktree / "vendor").mkdir()
    (worktree / "vendor" / "autoload.php").symlink_to(outside_file)

    runner = _FakeRunner()
    config = _host_config(
        artifacts=[{"path": "vendor/autoload.php", "kind": "file"}]
    )
    provider = ComposerProvider(config, worktree_path=worktree, runner=runner)
    # readiness_ok() is a read-only probe: escape => not ready, never raises.
    assert provider.readiness_ok() is False


def test_h2_legit_writable_path_still_works(tmp_path: Path) -> None:
    """Regression guard: the boundary check must not break the ordinary,
    non-symlinked writable-path case."""

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    runner = _FakeRunner()
    config = _host_config(writable_paths=["storage/logs"])
    provider = ComposerProvider(config, worktree_path=worktree, runner=runner)
    provider.provision()
    assert (worktree / "storage" / "logs").is_dir()
    assert runner.specs, "composer should have run after a successful probe"
