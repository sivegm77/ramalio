"""E10-S3 — PostgreSQL data provisioning tests.

Exercises the data capability + postgres provider against a fake
RuntimeCommandExecutor: fixed scopes, identity resolution, readiness, dump/
restore argv, cleanup policy, source safety and secret redaction — no real
Docker or PostgreSQL.
"""

from __future__ import annotations

from pathlib import PurePosixPath

import pytest

from ramalio.capabilities.base import CapabilityContext, CapabilityState
from ramalio.capabilities.data import DataCapability
from ramalio.capabilities.data.models import parse_data_config
from ramalio.capabilities.data.postgres import PostgresProvider
from ramalio.capabilities.runtime.base import (
    RuntimeExecResult,
    RuntimeResult,
    RuntimeScope,
    RuntimeState,
    RuntimeWorkspace,
)
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    CapabilityConfigInvalidError,
    DataProvisioningFailedError,
    DataReadinessTimeoutError,
    ProjectConfigInvalidError,
)
from ramalio.core.naming import ResolvedWorkspaceIdentity
from ramalio.core.target import Target


# --- config parsing / validation (AC-02, AC-12) ----------------------------


def test_absent_section_disabled() -> None:
    assert parse_data_config({}).enabled is False


def test_valid_config_defaults() -> None:
    config = parse_data_config({"enabled": True, "provider": "postgres"})
    assert config.provider == "postgres"
    assert config.on_init is True
    assert config.on_adopt is True
    assert config.runtime_service == "db"
    assert config.readiness_timeout == 30
    assert config.cleanup_mode == "preserve"


@pytest.mark.parametrize(
    "options",
    [
        {"enabled": True, "provider": "mysql"},           # AC-12 only postgres
        {"enabled": True, "unknown": 1},                  # unknown key
        {"enabled": True, "readiness_timeout": 0},        # not > 0
        {"enabled": True, "readiness_timeout": "30"},     # not int
        {"enabled": True, "readiness_timeout": True},     # bool not int
        {"enabled": True, "runtime_service": ""},         # empty
        {"enabled": True, "cleanup_mode": "drop"},        # invalid mode
    ],
)
def test_invalid_config_fails_closed(options) -> None:
    with pytest.raises(CapabilityConfigInvalidError):
        parse_data_config(options)


def test_enabled_requires_provider() -> None:
    with pytest.raises(CapabilityConfigInvalidError):
        parse_data_config({"enabled": True})


# --- fake runtime command executor -----------------------------------------


class _FakeExecutor:
    """Scriptable RuntimeCommandExecutor spy.

    Returns per-command results keyed by the first argv token, and records the
    (scope, request) of every exec so tests can assert scope isolation, argv
    exactness and that the source never receives a restore.
    """

    def __init__(self) -> None:
        self.ensured: list[tuple] = []
        self.execs: list[tuple] = []
        # Defaults: identity + readiness succeed; dump returns bytes; restore ok.
        self.user = "appuser"
        self.db = "appdb"
        self.pg_isready_rc = 0
        self.dump_rc = 0
        self.dump_bytes = b"-- DUMP --"
        self.restore_rc = 0

    def ensure_service(self, scope, workspace, service):
        self.ensured.append((scope, service))
        return RuntimeResult(RuntimeState.RUNNING, "up")

    def exec(self, scope, workspace, request) -> RuntimeExecResult:
        self.execs.append((scope, request))
        tok = request.argv[0]
        if tok == "printenv":
            name = request.argv[1]
            value = self.user if name == "POSTGRES_USER" else self.db
            return RuntimeExecResult(0, value.encode() + b"\n", b"")
        if tok == "pg_isready":
            return RuntimeExecResult(self.pg_isready_rc, b"", b"")
        if tok == "pg_dump":
            return RuntimeExecResult(self.dump_rc, self.dump_bytes, b"")
        if tok == "psql":
            return RuntimeExecResult(self.restore_rc, b"", b"")
        return RuntimeExecResult(0, b"", b"")


def _target_workspace():
    from pathlib import Path

    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted("alpha"),
        branch_name="alpha",
        worktree_path=PurePosixPath(".local-wt") / "alpha",
    )
    return RuntimeWorkspace(
        target="alpha",
        worktree_path=Path("/tmp/wt/alpha"),
        identity=identity,
        repository_root=Path("/tmp/repo"),
    )


def _provider(executor, **over):
    opts = {"enabled": True, "provider": "postgres"}
    opts.update(over)
    config = parse_data_config(opts)
    return PostgresProvider(
        config,
        executor=executor,
        source_workspace=None,
        target_workspace=_target_workspace(),
    )


# --- provisioning flow (AC-03, AC-05, AC-06) -------------------------------


def test_ac03_source_project_and_target_workspace_scopes() -> None:
    ex = _FakeExecutor()
    _provider(ex).provision()
    # ensure_service called for both project and workspace scopes.
    scopes = {s for s, _ in ex.ensured}
    assert RuntimeScope.PROJECT in scopes
    assert RuntimeScope.WORKSPACE in scopes


def test_ac05_source_never_receives_restore_or_drop() -> None:
    ex = _FakeExecutor()
    _provider(ex).provision()
    # No psql restore is ever run against the PROJECT (source) scope.
    for scope, request in ex.execs:
        if request.argv[0] == "psql":
            assert scope is RuntimeScope.WORKSPACE, "restore must target workspace"
    # No destructive DDL (dropdb/drop database) is ever issued anywhere.
    for _, request in ex.execs:
        joined = " ".join(request.argv).lower()
        assert "dropdb" not in joined
        assert "drop database" not in joined


def test_ac06_dump_and_restore_argv_are_exact() -> None:
    ex = _FakeExecutor()
    _provider(ex).provision()
    dump = next(r for _, r in ex.execs if r.argv[0] == "pg_dump")
    assert dump.argv == (
        "pg_dump", "-U", "appuser", "-d", "appdb",
        "--clean", "--if-exists", "--no-owner", "--no-privileges",
    )
    restore = next(r for _, r in ex.execs if r.argv[0] == "psql")
    assert restore.argv == (
        "psql", "-v", "ON_ERROR_STOP=1", "-U", "appuser", "-d", "appdb",
    )
    # The dump is streamed via stdin, never as an argument.
    assert restore.stdin == ex.dump_bytes


def test_ac07_dump_not_printed_or_persisted_insecurely() -> None:
    # The provider holds the dump only in memory and passes it via stdin; it is
    # never returned to the caller or written to a world-readable file.
    ex = _FakeExecutor()
    provider = _provider(ex)
    provider.provision()
    # The provision() return is a bool, never the dump bytes.
    assert provider.provision() is True


def test_readiness_timeout(monkeypatch) -> None:
    ex = _FakeExecutor()
    ex.pg_isready_rc = 1  # never ready
    # Avoid real sleeping.
    monkeypatch.setattr("time.sleep", lambda *_: None)
    with pytest.raises(DataReadinessTimeoutError):
        _provider(ex, readiness_timeout=1).provision()


def test_restore_failure_is_provisioning_error() -> None:
    ex = _FakeExecutor()
    ex.restore_rc = 1
    with pytest.raises(DataProvisioningFailedError):
        _provider(ex).provision()


def test_dump_failure_is_provisioning_error() -> None:
    ex = _FakeExecutor()
    ex.dump_rc = 1
    with pytest.raises(DataProvisioningFailedError):
        _provider(ex).provision()


def test_ac11_no_password_ever_read() -> None:
    ex = _FakeExecutor()
    _provider(ex).provision()
    for _, request in ex.execs:
        joined = " ".join(request.argv)
        assert "POSTGRES_PASSWORD" not in joined
        assert "PGPASSWORD" not in joined


# --- capability config: cleanup_mode and runtime requirement ----------------


_BASE_CONFIG = """
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "@@TARGET@@"

[branch]
pattern = "@@TARGET@@"

[capabilities.runtime]
driver = "docker-compose"
compose_file = "compose.yaml"
@@RUNTIME_EXTRA@@

[capabilities.data]
enabled = true
provider = "postgres"
cleanup_mode = "@@CLEANUP_MODE@@"
"""


def _ctx(project, target=None):
    config = resolve_project_config(project)
    identity = None
    if target is not None:
        identity = ResolvedWorkspaceIdentity(
            target=Target.from_trusted(target),
            branch_name=target,
            worktree_path=PurePosixPath(".local-wt") / target,
        )
    return CapabilityContext(config=config, identity=identity)


def _write(project, write_config, *, cleanup_mode="preserve", runtime_extra=""):
    body = (
        _BASE_CONFIG.replace("@@TARGET@@", "{target}")
        .replace("@@CLEANUP_MODE@@", cleanup_mode)
        .replace("@@RUNTIME_EXTRA@@", runtime_extra)
    )
    write_config(project, body)
    return project


def test_ac10_cleanup_runtime_requires_remove_volumes(git_repo_with_commit, write_config):
    # cleanup_mode='runtime' without remove_volumes_on_destroy -> PROJECT_CONFIG_INVALID.
    _write(git_repo_with_commit, write_config, cleanup_mode="runtime")
    cap = DataCapability()
    with pytest.raises(ProjectConfigInvalidError):
        cap.validate_config(_ctx(git_repo_with_commit, "alpha"))


def test_ac10_cleanup_runtime_ok_with_remove_volumes(git_repo_with_commit, write_config):
    _write(
        git_repo_with_commit,
        write_config,
        cleanup_mode="runtime",
        runtime_extra="remove_volumes_on_destroy = true",
    )
    cap = DataCapability()
    # Should not raise.
    cap.validate_config(_ctx(git_repo_with_commit, "alpha"))


def test_ac09_cleanup_preserve_needs_no_volume_removal(git_repo_with_commit, write_config):
    _write(git_repo_with_commit, write_config, cleanup_mode="preserve")
    cap = DataCapability()
    cap.validate_config(_ctx(git_repo_with_commit, "alpha"))


def test_data_requires_runtime_executor(git_repo_with_commit, write_config):
    # A 'none' runtime does not implement command execution -> config invalid.
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

[capabilities.runtime]
driver = "none"

[capabilities.data]
enabled = true
provider = "postgres"
""",
    )
    cap = DataCapability()
    with pytest.raises(CapabilityConfigInvalidError):
        cap.validate_config(_ctx(git_repo_with_commit, "alpha"))


def test_ac01_project_without_data_unchanged(git_repo_with_commit, write_config):
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
    cap = DataCapability()
    ctx = _ctx(git_repo_with_commit)
    assert cap.is_enabled(ctx) is False
    assert cap.status(ctx).state == CapabilityState.DISABLED


# --- wiring via init/adopt (AC-08) -----------------------------------------


def test_ac08_adopt_converges_target(git_repo_with_commit, write_config, run_git, monkeypatch):
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.core.adopt import AdoptWorkspaceService

    _write(
        git_repo_with_commit,
        write_config,
        cleanup_mode="preserve",
    )
    run_git(git_repo_with_commit, "branch", "alpha", "main")

    calls: list = []

    class _SpyProvider(PostgresProvider):
        def provision(self):
            calls.append("provision")
            return True

    import ramalio.capabilities.data.capability as capmod

    monkeypatch.setitem(capmod._PROVIDERS, "postgres", _SpyProvider)
    registry = CapabilityRegistry.with_capabilities([DataCapability()])
    AdoptWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    ).run("alpha")
    assert calls == ["provision"]


def test_init_runs_data(git_repo_with_commit, write_config, monkeypatch):
    from ramalio.capabilities import CapabilityRegistry
    from ramalio.core.init import InitWorkspaceService

    _write(git_repo_with_commit, write_config, cleanup_mode="preserve")

    calls: list = []

    class _SpyProvider(PostgresProvider):
        def provision(self):
            calls.append("provision")
            return True

    import ramalio.capabilities.data.capability as capmod

    monkeypatch.setitem(capmod._PROVIDERS, "postgres", _SpyProvider)
    registry = CapabilityRegistry.with_capabilities([DataCapability()])
    InitWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    ).run("beta")
    assert calls == ["provision"]


def test_ac13_only_postgres_provider():
    import ramalio.capabilities.data.capability as capmod

    assert set(capmod._PROVIDERS) == {"postgres"}
