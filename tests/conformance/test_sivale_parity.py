"""SiVale lifecycle parity matrix — DETERMINISTIC conformance level (E8-S1).

Reproducible scenarios comparing the guarantees of SiVale's existing worktree
lifecycle against `ramalio` + SiVale configuration.  External tools are faked so
the parity matrix runs deterministically in CI (E7-S3 R19); the invariants under
test are the ones that must be preserved (spec section 5).

SCOPE AND LIMITS (read before citing this as E8 closure):
    This suite intentionally uses ``runtime = "none"``, an always-free port
    probe and no real tmux/Kiro, and it runs inits sequentially.  It proves the
    *invariants* hold in a deterministic environment, but it is NOT the
    operational pilot E8-S1 also requires (real docker-compose runtime, real
    ports, tmux/Kiro enabled and genuinely concurrent worktrees).  That real
    evidence is produced out of CI by ``scripts/validate-sivale-pilot.sh`` and
    recorded under ``docs/evidence/``.

    Partial-failure / rollback is deliberately NOT part of the operational
    pilot: it is covered here deterministically (via injected hook failures)
    and by the E7 conformance suite, because fabricating a real partial failure
    is non-reproducible.  A real partial-failure sample, if ever wanted, is an
    optional/manual step, not a pilot requirement.
    See ``docs/examples/sivale-parity-matrix.md`` for the split.

Each test asserts a parity invariant and is referenced by
docs/examples/sivale-parity-matrix.md.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ramalio.capabilities import (
    BaseCapability,
    CapabilityContext,
    CapabilityRegistry,
    CapabilityState,
)
from ramalio.capabilities.base import CapabilityStatus
from ramalio.capabilities.ports_capability import PortsCapability
from ramalio.config.loader import resolve_project_config
from ramalio.core.destroy import DestroyWorkspaceService
from ramalio.core.errors import (
    DestroyBlockedDirtyError,
    WorkspaceAlreadyExistsError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.startstop import StartWorkspaceService, StopWorkspaceService
from ramalio.git.repository import GitRepository

# A SiVale-like config that uses only faked-friendly capabilities so the matrix
# runs without docker/tmux/kiro. Runtime uses the 'none' driver; ports enabled.
_SIVALE_LIKE = """
[project]
name = "sivale-zurich"
base_branch = "main"

[target]
regex = "^E[0-9]+-S[0-9]+-[a-z0-9]+(-[a-z0-9]+)*$"
example = "E7-S8-convergencia-schema-tests"
case_sensitive = true

[target.normalization]
trim = true
lowercase_slug = true
replace_spaces = "-"
collapse_dashes = true
slug_separator = "-"
preserve_prefix_segments = 2

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "spec/{target}"

[ports]
enabled = true
start = 8100
size = 20

[capabilities.runtime]
driver = "none"
"""

_TARGET_A = "E7-S1-alpha"
_TARGET_B = "E7-S2-bravo"


def _make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "sivale"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    import os

    for k, v in {
        "GIT_AUTHOR_NAME": "c",
        "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c",
        "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    (root / ".ramalio.toml").write_text(_SIVALE_LIKE, encoding="utf-8")
    return root


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _make_repo(tmp_path)


def _registry(state_base: Path) -> CapabilityRegistry:
    # Ports (real allocator with an always-free probe) + the none runtime.
    from ramalio.capabilities.runtime import RuntimeCapability

    return CapabilityRegistry.with_capabilities(
        [
            PortsCapability(store_base=state_base, port_probe=lambda p: True),
            RuntimeCapability(),
        ]
    )


def _wt(repo: Path, target: str) -> Path:
    return (repo / ".local-wt" / target).resolve()


# --- init nuevo (AC-01) ----------------------------------------------------


def test_init_new(repo: Path, tmp_path: Path) -> None:
    reg = _registry(tmp_path / "state")
    InitWorkspaceService(resolve_project_config(repo), registry=reg).run(_TARGET_A)
    g = GitRepository.from_root(repo)
    assert g.branch_exists(f"spec/{_TARGET_A}")
    assert g.get_worktree_by_path(_wt(repo, _TARGET_A)) is not None


# --- init duplicado --------------------------------------------------------


def test_init_duplicate_blocked(repo: Path, tmp_path: Path) -> None:
    reg = _registry(tmp_path / "state")
    cfg = resolve_project_config(repo)
    InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    with pytest.raises(WorkspaceAlreadyExistsError):
        InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)


# --- adopt branch-only (AC-02) ---------------------------------------------


def test_adopt_branch_only(repo: Path, tmp_path: Path) -> None:
    from ramalio.core.adopt import AdoptWorkspaceService

    subprocess.run(
        ["git", "-C", str(repo), "branch", f"spec/{_TARGET_A}", "main"],
        check=True,
        capture_output=True,
    )
    outcome = AdoptWorkspaceService(resolve_project_config(repo)).run(_TARGET_A)
    assert outcome.adoption_mode == "created-worktree"


# --- 2 worktrees paralelos + puertos no colisionan (AC-03) -----------------


def test_two_parallel_workspaces_isolated(repo: Path, tmp_path: Path) -> None:
    reg = _registry(tmp_path / "state")
    cfg = resolve_project_config(repo)
    InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    InitWorkspaceService(cfg, registry=reg).run(_TARGET_B)

    from ramalio.resources.ports import PortReservationStore

    store = PortReservationStore(repo, base=tmp_path / "state")
    pa = store.load(_TARGET_A)
    pb = store.load(_TARGET_B)
    assert pa is not None and pb is not None
    # Distinct branches, paths and ports (invariant 3).
    assert pa.port != pb.port
    g = GitRepository.from_root(repo)
    assert g.get_worktree_by_path(_wt(repo, _TARGET_A)) is not None
    assert g.get_worktree_by_path(_wt(repo, _TARGET_B)) is not None


# --- start/stop (AC-04) ----------------------------------------------------


def test_start_stop_preserve_identity(repo: Path, tmp_path: Path) -> None:
    reg = _registry(tmp_path / "state")
    cfg = resolve_project_config(repo)
    InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    StartWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    StopWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    # Invariant 6/7: branch + worktree preserved across stop/start.
    g = GitRepository.from_root(repo)
    assert g.branch_exists(f"spec/{_TARGET_A}")
    assert g.get_worktree_by_path(_wt(repo, _TARGET_A)) is not None


# --- destroy dirty bloqueado (AC-05) ---------------------------------------


def test_destroy_dirty_blocked(repo: Path, tmp_path: Path) -> None:
    reg = _registry(tmp_path / "state")
    cfg = resolve_project_config(repo)
    InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    # Dirty the worktree.
    (_wt(repo, _TARGET_A) / "README.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(DestroyBlockedDirtyError):
        DestroyWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    # Work preserved (invariant 5).
    assert (_wt(repo, _TARGET_A) / "README.md").read_text(encoding="utf-8") == "changed\n"


# --- destroy clean + releases port -----------------------------------------


def test_destroy_clean_releases_resources(repo: Path, tmp_path: Path) -> None:
    reg = _registry(tmp_path / "state")
    cfg = resolve_project_config(repo)
    InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    from ramalio.resources.ports import PortReservationStore

    store = PortReservationStore(repo, base=tmp_path / "state")
    assert store.load(_TARGET_A) is not None
    DestroyWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    g = GitRepository.from_root(repo)
    assert g.get_worktree_by_path(_wt(repo, _TARGET_A)) is None
    # R7: port released on destroy.
    assert store.load(_TARGET_A) is None


# --- fallo parcial + rollback (AC-06) --------------------------------------


class _FailAfterInit(BaseCapability):
    capability_name = "faildummy"

    def is_enabled(self, context) -> bool:
        return True

    def handle(self, event: str, context: object) -> object:
        if event == "after_init":
            raise RuntimeError("induced failure")
        return None


def test_partial_failure_rolls_back(repo: Path, tmp_path: Path) -> None:
    from ramalio.core.errors import CapabilityHookFailedError

    reg = CapabilityRegistry.with_capabilities(
        [
            PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True),
            _FailAfterInit(),
        ]
    )
    cfg = resolve_project_config(repo)
    with pytest.raises(CapabilityHookFailedError):
        InitWorkspaceService(cfg, registry=reg).run(_TARGET_A)
    # Invariant 4: partial failure destroys no preexisting resource and rolls
    # back the Git workspace this init created.
    g = GitRepository.from_root(repo)
    assert not g.branch_exists(f"spec/{_TARGET_A}")
    assert g.get_worktree_by_path(_wt(repo, _TARGET_A)) is None



# ===========================================================================
# E10 provisioning parity (deterministic): the real SiVale E10 configuration
# drives runtime provisioning, PostgreSQL data provisioning and Composer
# dependency/readiness during init/adopt, with faked external tools so the
# matrix stays reproducible in CI (E10-S4 R9 deterministic level).
# ===========================================================================

_SIVALE_E10_TOML = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "sivale.ramalio.toml"
).read_text(encoding="utf-8")


def _make_e10_repo(tmp_path: Path) -> Path:
    root = tmp_path / "sivale-e10"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    import os

    for k, v in {
        "GIT_AUTHOR_NAME": "c",
        "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c",
        "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    (root / ".ramalio.toml").write_text(_SIVALE_E10_TOML, encoding="utf-8")
    return root


class _FakeExecutorDriver:
    """A runtime driver + RuntimeCommandExecutor that records provisioning ops.

    Stands in for docker-compose so the SiVale E10 config can be exercised end
    to end deterministically: it records provision()/ensure_service()/exec() and
    answers the postgres provider's printenv/pg_isready probes so data
    provisioning completes.
    """

    def __init__(self) -> None:
        self.ops: list[str] = []

    @property
    def name(self) -> str:
        return "docker-compose"

    # RuntimeDriver
    def doctor(self, workspace):
        from ramalio.capabilities.runtime.base import RuntimeDoctorCheck

        return (RuntimeDoctorCheck("FAKE", True, "ok"),)

    def status(self, workspace):
        from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

        return RuntimeResult(RuntimeState.STOPPED, "stopped")

    def provision(self, workspace):
        from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

        self.ops.append("runtime.provision")
        return RuntimeResult(RuntimeState.RUNNING, "provisioned", changed=True)

    def start(self, workspace):
        from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

        return RuntimeResult(RuntimeState.RUNNING, "up", changed=True)

    def stop(self, workspace):
        from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

        return RuntimeResult(RuntimeState.STOPPED, "stop", changed=True)

    def cleanup(self, workspace):
        from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

        self.ops.append("runtime.cleanup")
        return RuntimeResult(RuntimeState.STOPPED, "down -v", changed=True)

    @property
    def remove_volumes_on_destroy(self) -> bool:
        return True

    @property
    def provision_on_init(self) -> bool:
        return True

    @property
    def provision_on_adopt(self) -> bool:
        return True

    # RuntimeCommandExecutor
    def ensure_service(self, scope, workspace, service):
        from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

        self.ops.append(f"ensure:{scope.value}:{service}")
        return RuntimeResult(RuntimeState.RUNNING, "up")

    def exec(self, scope, workspace, request):
        from ramalio.capabilities.runtime.base import RuntimeExecResult

        tok = request.argv[0]
        self.ops.append(f"exec:{tok}")
        if tok == "printenv":
            name = request.argv[1]
            value = "appuser" if name == "POSTGRES_USER" else "appdb"
            return RuntimeExecResult(0, value.encode() + b"\n", b"")
        # pg_isready, pg_dump, psql, composer, sh probe: all succeed.
        if tok == "pg_dump":
            return RuntimeExecResult(0, b"-- DUMP --", b"")
        return RuntimeExecResult(0, b"", b"")


def _e10_registry(driver, state_base: Path):
    """Registry with the SiVale capability set, faking the docker driver.

    Ports use an always-free probe; runtime resolves the fake docker-compose
    driver (which also implements RuntimeCommandExecutor); data + bootstrap use
    their real capabilities but run through the fake executor. Bootstrap runs a
    fake provider so no real Composer/artifacts are needed.
    """
    from ramalio.capabilities.bootstrap import BootstrapCapability
    from ramalio.capabilities.data import DataCapability
    from ramalio.capabilities.runtime import RuntimeCapability

    runtime_cap = RuntimeCapability(
        drivers={"docker-compose": lambda _o, _c=None: driver}
    )
    return CapabilityRegistry.with_capabilities(
        [
            PortsCapability(store_base=state_base, port_probe=lambda p: True),
            runtime_cap,
            DataCapability(),
            BootstrapCapability(),
            _FakeTmux(),
        ]
    )


class _FakeTmux(BaseCapability):
    """Benign tmux stand-in so the SiVale config (which enables tmux) validates
    and runs without a real tmux binary in CI."""

    capability_name = "tmux"

    def is_enabled(self, context) -> bool:
        return context.capability_config(self.name) is not None

    def handle(self, event: str, context: object) -> object:
        return None


def test_e10_init_drives_full_provisioning(repo_e10, tmp_path, monkeypatch) -> None:
    """`init` with the SiVale E10 config performs runtime provisioning, data
    provisioning (via the runtime executor) and Composer bootstrap (R1)."""
    from ramalio.capabilities.bootstrap.composer import ComposerProvider
    import ramalio.capabilities.bootstrap.capability as bootcap
    import ramalio.capabilities.runtime.capability as rtcap

    driver = _FakeExecutorDriver()
    # Register the fake docker-compose driver GLOBALLY (the production seam), so
    # data/bootstrap resolve the same executor the runtime uses.
    monkeypatch.setitem(rtcap._DRIVERS, "docker-compose", lambda _o, _c=None: driver)

    # Fake Composer provider that records instead of running the real tool.
    bootstrap_ops: list[str] = []

    class _SpyComposer(ComposerProvider):
        def provision(self, *, executor=None, scope=None, workspace=None):
            bootstrap_ops.append("bootstrap.provision")

    monkeypatch.setitem(bootcap._PROVIDERS, "composer", _SpyComposer)

    reg = _e10_registry(driver, tmp_path / "state")
    InitWorkspaceService(resolve_project_config(repo_e10), registry=reg).run(_TARGET_A)

    # Runtime provisioned during init.
    assert "runtime.provision" in driver.ops
    # Data provisioning ensured both scopes and ran dump + restore via executor.
    assert any(o.startswith("ensure:project:db") for o in driver.ops)
    assert any(o.startswith("ensure:workspace:db") for o in driver.ops)
    assert "exec:pg_dump" in driver.ops
    assert "exec:psql" in driver.ops
    # Composer dependency provisioning ran.
    assert bootstrap_ops == ["bootstrap.provision"]


def test_e10_adopt_completes_provisioning(repo_e10, tmp_path, monkeypatch) -> None:
    """`adopt` for a preexisting branch completes the equivalent provisioning
    (R2): runtime provision + data provision + bootstrap all run."""
    from ramalio.core.adopt import AdoptWorkspaceService
    from ramalio.capabilities.bootstrap.composer import ComposerProvider
    import ramalio.capabilities.bootstrap.capability as bootcap
    import ramalio.capabilities.runtime.capability as rtcap

    subprocess.run(
        ["git", "-C", str(repo_e10), "branch", f"spec/{_TARGET_A}", "main"],
        check=True,
        capture_output=True,
    )
    driver = _FakeExecutorDriver()
    monkeypatch.setitem(rtcap._DRIVERS, "docker-compose", lambda _o, _c=None: driver)
    bootstrap_ops: list[str] = []

    class _SpyComposer(ComposerProvider):
        def provision(self, *, executor=None, scope=None, workspace=None):
            bootstrap_ops.append("bootstrap.provision")

    monkeypatch.setitem(bootcap._PROVIDERS, "composer", _SpyComposer)

    reg = _e10_registry(driver, tmp_path / "state")
    outcome = AdoptWorkspaceService(
        resolve_project_config(repo_e10), registry=reg
    ).run(_TARGET_A)

    assert outcome.adoption_mode == "created-worktree"
    assert "runtime.provision" in driver.ops
    assert "exec:pg_dump" in driver.ops
    assert bootstrap_ops == ["bootstrap.provision"]


def test_e10_config_is_accepted_by_default_registry(repo_e10) -> None:
    """The real SiVale E10 config validates against the PRODUCTION default
    registry (no fakes), proving the capabilities accept it (R1/AC-03)."""
    from ramalio.capabilities import (
        default_registry,
        verify_capability_configuration,
    )
    from ramalio.config.target import (
        build_target_normalizer,
        build_workspace_naming,
    )

    cfg = resolve_project_config(repo_e10)
    identity = build_workspace_naming(cfg).resolve(
        build_target_normalizer(cfg).normalize(_TARGET_A).target
    )
    # Must not raise: runtime/data/bootstrap/tmux all accept the SiVale config,
    # including the data cleanup_mode='runtime' precondition (remove_volumes).
    verify_capability_configuration(default_registry(), cfg, identity)


@pytest.fixture
def repo_e10(tmp_path: Path) -> Path:
    return _make_e10_repo(tmp_path)
