"""End-to-end wiring regression tests (E6/E7).

These tests target the *wiring* the audit found missing: the individual
components (SafePathResolver, LockManager, LifecycleTransaction, PortAllocator
lock, DockerComposeDriver, hook ordering, zrok identity) were correct in
isolation but were not actually connected to the real lifecycle.  Every test
here exercises the production path (real services / real capability registry),
not a component configured by hand.

State (locks/ports/tunnels) is redirected to a temporary XDG_STATE_HOME so the
tests stay hermetic and never touch the developer's real state directory.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from ramalio.capabilities import CapabilityRegistry, default_registry
from ramalio.capabilities.base import CapabilityContext
from ramalio.config.loader import resolve_project_config
from ramalio.core.adopt import AdoptWorkspaceService
from ramalio.core.destroy import DestroyWorkspaceService
from ramalio.core.errors import (
    CapabilityUnknownError,
    DerivedWorktreePathInvalidError,
    LockTimeoutError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.startstop import StartWorkspaceService, StopWorkspaceService
from ramalio.git.repository import GitRepository
from ramalio.hooks import HookResult, LifecycleEvent
from ramalio.resources.locks import LockKey, LockManager, LockScope

_BASE_CONFIG = """
[project]
name = "wiring-proj"
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
def state_home(tmp_path: Path, monkeypatch) -> Path:
    state = tmp_path / "xdg-state"
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    return state


@pytest.fixture
def project(git_repo_with_commit: Path, write_config, state_home: Path) -> Path:
    write_config(git_repo_with_commit, _BASE_CONFIG)
    return git_repo_with_commit


# --- E7-S2: symlink escape blocked in init BEFORE any mutation -------------


def test_init_rejects_symlink_escape_before_mutation(
    git_repo_with_commit: Path, write_config, state_home: Path, tmp_path_factory
) -> None:
    # An external directory OUTSIDE the repository root.
    outside = tmp_path_factory.mktemp("external-escape")
    link = git_repo_with_commit / ".local-wt"
    link.symlink_to(outside)

    write_config(git_repo_with_commit, _BASE_CONFIG)
    cfg = resolve_project_config(git_repo_with_commit)

    with pytest.raises(DerivedWorktreePathInvalidError):
        InitWorkspaceService(cfg).run("feat-a")

    # Nothing was created: no branch, and the external dir stays empty.
    repo = GitRepository.from_root(git_repo_with_commit)
    assert not repo.branch_exists("feat-a")
    assert list(outside.iterdir()) == []


# --- E4-S0 R13: unknown capability blocks init before mutation -------------


def test_init_rejects_unknown_capability_before_mutation(
    git_repo_with_commit: Path, write_config, state_home: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _BASE_CONFIG + "\n[capabilities.mystery]\nenabled = true\n",
    )
    cfg = resolve_project_config(git_repo_with_commit)

    with pytest.raises(CapabilityUnknownError):
        InitWorkspaceService(cfg).run("feat-a")

    # Fail-closed: the workspace must not have been created by a typo'd cap.
    repo = GitRepository.from_root(git_repo_with_commit)
    assert not repo.branch_exists("feat-a")


def test_adopt_rejects_unknown_capability(
    project: Path, write_config, state_home: Path, run_git
) -> None:
    # Pre-create a branch so adopt has something to consider, then enable an
    # unknown capability: adopt must reject before touching Git.
    run_git(project, "branch", "feat-b", "main")
    write_config(project, _BASE_CONFIG + "\n[capabilities.mystery]\nenabled = true\n")
    cfg = resolve_project_config(project)
    with pytest.raises(CapabilityUnknownError):
        AdoptWorkspaceService(cfg).run("feat-b")


def test_start_rejects_unknown_capability(
    project: Path, write_config, state_home: Path
) -> None:
    # Build a real READY workspace under the default registry first.
    InitWorkspaceService(resolve_project_config(project)).run("feat-start")
    # Now enable an unknown capability and attempt start: it must fail closed
    # (E4-S0 R13) instead of silently running only the known capabilities.
    write_config(
        project, _BASE_CONFIG + "\n[capabilities.mystery]\nenabled = true\n"
    )
    cfg = resolve_project_config(project)
    with pytest.raises(CapabilityUnknownError):
        StartWorkspaceService(cfg).run("feat-start")


def test_stop_rejects_unknown_capability(
    project: Path, write_config, state_home: Path
) -> None:
    InitWorkspaceService(resolve_project_config(project)).run("feat-stop")
    write_config(
        project, _BASE_CONFIG + "\n[capabilities.mystery]\nenabled = true\n"
    )
    cfg = resolve_project_config(project)
    with pytest.raises(CapabilityUnknownError):
        StopWorkspaceService(cfg).run("feat-stop")


def test_destroy_rejects_unknown_capability(
    project: Path, write_config, state_home: Path
) -> None:
    InitWorkspaceService(resolve_project_config(project)).run("feat-destroy")
    write_config(
        project, _BASE_CONFIG + "\n[capabilities.mystery]\nenabled = true\n"
    )
    cfg = resolve_project_config(project)
    with pytest.raises(CapabilityUnknownError):
        DestroyWorkspaceService(cfg).run("feat-destroy")

    # Fail-closed: the workspace must still exist (nothing was destroyed).
    repo = GitRepository.from_root(project)
    assert repo.branch_exists("feat-destroy")


# --- E7-S1 R3: same-target lifecycle operations are mutually exclusive ------


def test_same_target_lock_serializes_init(project: Path, state_home: Path) -> None:
    cfg = resolve_project_config(project)
    manager = LockManager.for_repository(cfg.repository_root, timeout=0.2)

    # Hold the target lock for feat-a, then a real init of feat-a must time out
    # instead of racing (R3).
    key = LockKey(LockScope.TARGET, f"{cfg.repository_root}:feat-a")
    with manager.acquire(key, operation="test-hold"):
        service = InitWorkspaceService(cfg, lock_manager=manager)
        with pytest.raises(LockTimeoutError):
            service.run("feat-a")

    # Once released, the same init succeeds.
    service = InitWorkspaceService(cfg, lock_manager=manager)
    outcome = service.run("feat-a")
    assert outcome.branch == "feat-a"


# --- E7-S1 R4: distinct targets progress in parallel -----------------------


def test_different_targets_progress_in_parallel(
    project: Path, state_home: Path
) -> None:
    cfg = resolve_project_config(project)
    manager = LockManager.for_repository(cfg.repository_root, timeout=5.0)

    # Hold feat-a's target lock; an init of feat-b must NOT be blocked by it (R4).
    key_a = LockKey(LockScope.TARGET, f"{cfg.repository_root}:feat-a")
    with manager.acquire(key_a, operation="test-hold"):
        service = InitWorkspaceService(cfg, lock_manager=manager)
        outcome = service.run("feat-b")  # different target -> proceeds
    assert outcome.branch == "feat-b"


# --- E7-S1 R5: the port pool lock is wired through PortsCapability ----------


def test_port_pool_lock_used_by_capability(
    git_repo_with_commit: Path, write_config, state_home: Path
) -> None:
    # Enable ports and drive reservation through the real capability, while the
    # port-pool lock is held: the capability must block on it (proving it uses
    # the LockManager in production, not a lock-less allocator).
    write_config(
        git_repo_with_commit,
        _BASE_CONFIG
        + "\n[ports]\nenabled = true\nstart = 8100\nsize = 8\n",
    )
    cfg = resolve_project_config(git_repo_with_commit)

    from ramalio.capabilities.ports_capability import PortsCapability
    from ramalio.config.target import (
        build_target_normalizer,
        build_workspace_naming,
    )

    normalizer = build_target_normalizer(cfg)
    naming = build_workspace_naming(cfg)
    identity = naming.resolve(normalizer.normalize("feat-a").target)

    manager = LockManager.for_repository(cfg.repository_root, timeout=0.2)
    # Build the exact pool key the allocator uses.
    from ramalio.resources.ports import PortReservationStore

    store = PortReservationStore(cfg.repository_root)
    pool_key = LockKey(
        LockScope.PORT_POOL, f"{store.project_id}:{cfg.ports.start}:{cfg.ports.size}"
    )

    cap = PortsCapability()
    ctx = CapabilityContext(config=cfg, identity=identity)

    with manager.acquire(pool_key, operation="test-hold"):
        with pytest.raises(LockTimeoutError):
            cap.handle("after_init", type("C", (), {"capability_context": ctx})())


# --- E6-S2 R3/R9: docker driver receives real project name + reserved port --


def test_docker_driver_gets_project_name_and_reserved_port(
    git_repo_with_commit: Path, write_config, state_home: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _BASE_CONFIG
        + "\n[ports]\nenabled = true\nstart = 8200\nsize = 4\n"
        + '\n[capabilities.runtime]\nenabled = true\ndriver = "docker-compose"\n'
        + 'port_env = "APP_PORT"\n',
    )
    cfg = resolve_project_config(git_repo_with_commit)

    from ramalio.capabilities.runtime import RuntimeCapability
    from ramalio.config.target import (
        build_target_normalizer,
        build_workspace_naming,
    )
    from ramalio.resources.ports import PortAllocator, PortReservationStore

    normalizer = build_target_normalizer(cfg)
    naming = build_workspace_naming(cfg)
    identity = naming.resolve(normalizer.normalize("feat-a").target)

    # Reserve a port for feat-a so the driver's port_provider can find it.
    store = PortReservationStore(cfg.repository_root)
    reservation = PortAllocator(cfg.ports, store).reserve("feat-a")

    cap = RuntimeCapability()
    ctx = CapabilityContext(config=cfg, identity=identity)
    driver = cap._driver(ctx)  # production build path

    from ramalio.capabilities.runtime.base import RuntimeWorkspace

    ws = RuntimeWorkspace(
        target="feat-a",
        worktree_path=git_repo_with_commit / ".local-wt" / "feat-a",
        identity=identity,
        repository_root=cfg.repository_root,
    )
    # R3: project name uses the real [project].name, not the hardcoded "ramalio".
    assert driver.project_name(ws) == "wiring-proj-feat-a"
    # R9: the reserved port reaches the runtime env under the configured var.
    env = driver._env(ws)
    assert env.get("APP_PORT") == str(reservation.port)


# --- E6-S3 R13: teardown ordering (tunnel before runtime / ports) ----------


class _OrderCap:
    """Minimal capability that records the events it handles, by name."""

    def __init__(self, name: str, log: list[str]) -> None:
        self.capability_name = name
        self._log = log

    @property
    def name(self) -> str:
        return self.capability_name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return True

    def handle(self, event: str, context: object) -> object:
        self._log.append(f"{self.name}:{event}")
        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=event.startswith("after_") or event.startswith("before_"),
            summary="ok",
            compensation_available=False,
        )

    def compensate(self, event: str, context: object) -> None:  # pragma: no cover
        pass

    def validate_config(self, context: CapabilityContext) -> None:
        return None

    def status(self, context: CapabilityContext):  # pragma: no cover - unused
        raise NotImplementedError

    def doctor_checks(self, context: CapabilityContext):  # pragma: no cover
        return ()


def test_stop_tears_down_tunnel_before_runtime(
    project: Path, state_home: Path
) -> None:
    log: list[str] = []
    # Registration order mirrors production: runtime before tunnel.
    registry = CapabilityRegistry.with_capabilities(
        [_OrderCap("runtime", log), _OrderCap("tunnel", log)]
    )
    InitWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-order")

    log.clear()
    StopWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-order")

    # before_stop is a teardown event: tunnel must be handled before runtime.
    before_stop = [e for e in log if e.endswith("before_stop")]
    assert before_stop == ["tunnel:before_stop", "runtime:before_stop"]


def test_start_brings_up_runtime_before_tunnel(
    project: Path, state_home: Path
) -> None:
    log: list[str] = []
    registry = CapabilityRegistry.with_capabilities(
        [_OrderCap("runtime", log), _OrderCap("tunnel", log)]
    )
    InitWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-order2")

    log.clear()
    StartWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-order2")

    after_start = [e for e in log if e.endswith("after_start")]
    # Setup event keeps forward order: runtime up before tunnel.
    assert after_start == ["runtime:after_start", "tunnel:after_start"]


def test_destroy_tears_down_tunnel_before_ports(
    project: Path, state_home: Path
) -> None:
    log: list[str] = []
    # Production order: runtime, ports, tunnel. On destroy (teardown) the tunnel
    # must be cleaned before the port is released.
    registry = CapabilityRegistry.with_capabilities(
        [_OrderCap("runtime", log), _OrderCap("ports", log), _OrderCap("tunnel", log)]
    )
    InitWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-order3")

    log.clear()
    DestroyWorkspaceService(
        resolve_project_config(project), registry=registry
    ).run("feat-order3")

    before_destroy = [e for e in log if e.endswith("before_destroy")]
    assert before_destroy.index("tunnel:before_destroy") < before_destroy.index(
        "ports:before_destroy"
    )


# --- E6-S3 R7/R8/R9: zrok never signals a dead/reused PID ------------------


def test_zrok_stop_does_not_signal_unowned_pid(
    tmp_path: Path, state_home: Path
) -> None:
    from ramalio.capabilities.tunnels.base import (
        LocalEndpoint,
        TunnelWorkspace,
    )
    from ramalio.capabilities.tunnels.zrok import (
        TunnelRecord,
        TunnelStateStore,
        ZrokProvider,
    )

    signals: list[int] = []

    import ramalio.capabilities.tunnels.zrok as zrok_mod

    # Persist a tunnel record whose PID is dead/unowned directly (bypassing
    # start(), which now fails closed when no fingerprint can be captured, P7).
    # stop() must never signal such a PID (E6-S3 R9 ownership).
    store = TunnelStateStore(tmp_path, base=state_home)
    store.save(
        TunnelRecord(
            target="feat-a",
            pid=999999,
            public_url="https://example.zrok",
            start_time="0",  # will not match the (nonexistent) process
        )
    )

    provider = ZrokProvider(state_base=state_home)
    ws = TunnelWorkspace(
        target="feat-a",
        worktree_path=tmp_path,
        identity=None,
        repository_root=tmp_path,
    )

    # Patch os.kill to detect any signal attempt during stop.
    import os as _os

    orig_kill = _os.kill

    def spy_kill(pid, sig):
        # Record only real termination signals; os.kill(pid, 0) is a liveness
        # probe used by ownership checks and must not count as "signaling".
        if sig != 0:
            signals.append(pid)
        return orig_kill(pid, sig)

    zrok_mod.os.kill = spy_kill  # type: ignore[attr-defined]
    try:
        result = provider.stop(ws)
    finally:
        zrok_mod.os.kill = orig_kill  # type: ignore[attr-defined]

    # Stop is idempotent and never signaled the unowned/dead PID; the stale
    # ownership record is cleaned up.
    assert result.state.name == "STOPPED"
    assert signals == []
    assert store.load("feat-a") is None



# --- H2 (E7-S0): before_stop mutations are rolled back on failure ----------


class _StopCap:
    """Capability that mutates on before_stop, with configurable compensation
    and failure, recording every call in a shared log."""

    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        fail_before_stop: bool = False,
        compensation_available: bool = True,
    ) -> None:
        self.capability_name = name
        self._log = log
        self._fail = fail_before_stop
        self._comp = compensation_available

    @property
    def name(self) -> str:
        return self.capability_name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return True

    def handle(self, event: str, context: object):
        if event == "before_stop" and self._fail:
            raise RuntimeError(f"{self.name} boom on before_stop")
        if event == "before_stop":
            self._log.append(f"{self.name}:before_stop")
            return HookResult(
                capability=self.name,
                event=LifecycleEvent(event),
                success=True,
                changed=True,
                summary="stopped resource",
                compensation_available=self._comp,
            )
        return None

    def compensate(self, event: str, context: object) -> None:
        self._log.append(f"{self.name}:compensate:{event}")

    def validate_config(self, context: CapabilityContext) -> None:
        return None

    def status(self, context: CapabilityContext):  # pragma: no cover
        raise NotImplementedError

    def doctor_checks(self, context: CapabilityContext):  # pragma: no cover
        return ()


def test_before_stop_failure_compensates_prior_mutation(
    project: Path, state_home: Path
) -> None:
    from ramalio.core.errors import CapabilityHookFailedError

    log: list[str] = []
    # 'a' stops a resource (compensable); 'b' fails during before_stop. Because
    # teardown runs in reverse registration order, register b before a so a runs
    # first and records a compensable mutation, then b fails.
    reg = CapabilityRegistry.with_capabilities(
        [
            _StopCap("b", log, fail_before_stop=True),
            _StopCap("a", log, compensation_available=True),
        ]
    )
    InitWorkspaceService(
        resolve_project_config(project), registry=reg
    ).run("feat-stopfail")

    log.clear()
    with pytest.raises(CapabilityHookFailedError):
        StopWorkspaceService(
            resolve_project_config(project), registry=reg
        ).run("feat-stopfail")

    # The rollback ran even though the failure happened in before_stop: 'a'
    # (which mutated first) was compensated.
    assert "a:before_stop" in log
    assert "a:compensate:before_stop" in log


def test_before_stop_failure_non_compensable_is_not_lost(
    project: Path, state_home: Path
) -> None:
    from ramalio.core.errors import LifecycleRollbackIncompleteError

    log: list[str] = []
    reg = CapabilityRegistry.with_capabilities(
        [
            _StopCap("b", log, fail_before_stop=True),
            _StopCap("a", log, compensation_available=False),
        ]
    )
    InitWorkspaceService(
        resolve_project_config(project), registry=reg
    ).run("feat-stopunsafe")

    log.clear()
    # E7-S0 H2: a NOT_SAFE rollback (an owned mutation with no compensation)
    # surfaces as LifecycleRollbackIncompleteError, chained from the original
    # capability failure, instead of silently discarding the transaction
    # outcome.
    with pytest.raises(LifecycleRollbackIncompleteError) as exc:
        StopWorkspaceService(
            resolve_project_config(project), registry=reg
        ).run("feat-stopunsafe")

    assert exc.value.outcome == "ROLLBACK_NOT_SAFE"
    assert any("capability:a" in r for r in exc.value.unsafe_resources)
    # The original cause is preserved as __cause__ (never hidden).
    assert exc.value.__cause__ is not None

    # 'a' mutated but declared no compensation: it was NOT silently compensated,
    # and the failure still surfaced (the mutation is recorded as unsafe in the
    # transaction rather than lost). See test_hook_transaction_journal for the
    # transaction-level NOT_SAFE assertion.
    assert "a:before_stop" in log
    assert "a:compensate:before_stop" not in log



# --- H3 (E7-S0): destroy failure after irreversible removal ----------------


class _FailAfterDestroyCap:
    """Capability that fails on after_destroy (post irreversible removal)."""

    capability_name = "faildestroy"

    @property
    def name(self) -> str:
        return self.capability_name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return True

    def handle(self, event: str, context: object):
        if event == "after_destroy":
            raise RuntimeError("boom after destroy")
        return None

    def compensate(self, event: str, context: object) -> None:  # pragma: no cover
        pass

    def validate_config(self, context: CapabilityContext) -> None:
        return None

    def status(self, context: CapabilityContext):  # pragma: no cover
        raise NotImplementedError

    def doctor_checks(self, context: CapabilityContext):  # pragma: no cover
        return ()


def test_destroy_after_removal_failure_does_not_recreate_worktree(
    project: Path, state_home: Path
) -> None:
    from ramalio.core.errors import LifecycleRollbackIncompleteError

    reg = CapabilityRegistry.with_capabilities([_FailAfterDestroyCap()])
    InitWorkspaceService(
        resolve_project_config(project), registry=reg
    ).run("feat-destroyfail")

    # after_destroy fails AFTER the irreversible worktree removal. The failure
    # must surface diagnosably as ROLLBACK_NOT_SAFE (E7-S0 H2), and the worktree
    # is NOT magically recreated (E7-S0 R13: report unsafe, never recreate).
    with pytest.raises(LifecycleRollbackIncompleteError) as exc:
        DestroyWorkspaceService(
            resolve_project_config(project), registry=reg
        ).run("feat-destroyfail")

    assert exc.value.outcome == "ROLLBACK_NOT_SAFE"
    assert any("git:workspace" in r for r in exc.value.unsafe_resources)

    repo = GitRepository.from_root(project)
    wt = (project / ".local-wt" / "feat-destroyfail").resolve()
    assert repo.get_worktree_by_path(wt) is None  # removal was irreversible



# --- H1 (E7-S0): before_init mutations compensated when Git fails after ----


class _BeforeInitMutator:
    """Capability that mutates on before_init and records compensation calls."""

    capability_name = "beforeinit"

    def __init__(self, log: list[str], *, compensation_available: bool = True) -> None:
        self._log = log
        self._comp = compensation_available

    @property
    def name(self) -> str:
        return self.capability_name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return True

    def handle(self, event: str, context: object):
        if event != "before_init":
            return None
        self._log.append(f"{self.name}:before_init")
        return HookResult(
            capability=self.name,
            event=LifecycleEvent(event),
            success=True,
            changed=True,
            summary="reserved something before init",
            compensation_available=self._comp,
        )

    def compensate(self, event: str, context: object) -> None:
        self._log.append(f"{self.name}:compensate:{event}")

    def validate_config(self, context: CapabilityContext) -> None:
        return None

    def status(self, context: CapabilityContext):  # pragma: no cover
        raise NotImplementedError

    def doctor_checks(self, context: CapabilityContext):  # pragma: no cover
        return ()


def test_before_init_mutation_is_compensated_when_git_fails_after(
    project: Path, state_home: Path
) -> None:
    """A capability that mutates during before_init must be compensated if the
    central Git mutation fails afterward (E7-S0 H1): before_init now runs
    inside the same transaction as the rest of init, not outside it."""

    from ramalio.core.errors import InitGitOperationFailedError
    from ramalio.git.lifecycle import GitWriter

    log: list[str] = []

    class _FailingCreateBranchWriter(GitWriter):
        def create_branch(self, *, branch: str, base: str) -> None:
            raise GitCommandError_local("simulated branch creation failure")

    # Local import to avoid a hard dependency ordering issue in this test file.
    from ramalio.core.errors import GitCommandError as GitCommandError_local

    reg = CapabilityRegistry.with_capabilities([_BeforeInitMutator(log)])
    cfg = resolve_project_config(project)
    writer = _FailingCreateBranchWriter(cfg.repository_root)
    service = InitWorkspaceService(cfg, registry=reg, writer=writer)

    with pytest.raises(InitGitOperationFailedError):
        service.run("feat-beforeinit")

    # The before_init mutation was rolled back even though the failure happened
    # in the central Git step, not in a capability hook.
    assert "beforeinit:before_init" in log
    assert "beforeinit:compensate:before_init" in log


def test_before_init_non_compensable_mutation_surfaces_as_unsafe(
    project: Path, state_home: Path
) -> None:
    from ramalio.core.errors import (
        GitCommandError,
        InitGitOperationFailedError,
        LifecycleRollbackIncompleteError,
    )
    from ramalio.git.lifecycle import GitWriter

    log: list[str] = []

    class _FailingCreateBranchWriter(GitWriter):
        def create_branch(self, *, branch: str, base: str) -> None:
            raise GitCommandError("simulated branch creation failure")

    reg = CapabilityRegistry.with_capabilities(
        [_BeforeInitMutator(log, compensation_available=False)]
    )
    cfg = resolve_project_config(project)
    writer = _FailingCreateBranchWriter(cfg.repository_root)
    service = InitWorkspaceService(cfg, registry=reg, writer=writer)

    # A non-compensable before_init mutation combined with a later Git failure
    # must surface as an unsafe rollback rather than silently succeeding as a
    # plain InitGitOperationFailedError.
    with pytest.raises(LifecycleRollbackIncompleteError) as exc:
        service.run("feat-beforeinitunsafe")

    assert exc.value.outcome == "ROLLBACK_NOT_SAFE"
    assert any("capability:beforeinit" in r for r in exc.value.unsafe_resources)
    assert isinstance(exc.value.__cause__, InitGitOperationFailedError)



# --- H3 (E6-S1): ports participate in start, not only init -----------------


def test_adopted_workspace_gets_port_on_start(
    project: Path, write_config, state_home: Path, run_git
) -> None:
    """A workspace created via `adopt` (which never runs capability hooks)
    must still receive a port reservation once `start` runs, since `adopt`
    is not the only way a workspace enters the lifecycle (E6-S1 R10)."""

    write_config(
        project, _BASE_CONFIG + "\n[ports]\nenabled = true\nstart = 8300\nsize = 5\n"
    )
    cfg = resolve_project_config(project)
    from ramalio.capabilities.ports_capability import PortsCapability
    from ramalio.resources.ports import PortReservationStore

    reg = CapabilityRegistry.with_capabilities(
        [PortsCapability(port_probe=lambda p: True)]
    )

    run_git(project, "branch", "feat-portadopt", "main")
    AdoptWorkspaceService(cfg, registry=reg).run("feat-portadopt")

    store = PortReservationStore(cfg.repository_root)
    assert store.load("feat-portadopt") is None  # adopt never runs hooks

    from ramalio.core.startstop import StartWorkspaceService

    outcome = StartWorkspaceService(cfg, registry=reg).run("feat-portadopt")
    assert outcome.resources_started >= 1

    reservation = store.load("feat-portadopt")
    assert reservation is not None


def test_start_does_not_reallocate_existing_port(
    project: Path, write_config, state_home: Path
) -> None:
    """`start` must reuse an existing reservation (from init) rather than
    allocating a new one, and must not compensate/release it on a later
    failure since it does not own it (E6-S1 R10)."""

    write_config(
        project, _BASE_CONFIG + "\n[ports]\nenabled = true\nstart = 8400\nsize = 5\n"
    )
    cfg = resolve_project_config(project)
    from ramalio.capabilities.ports_capability import PortsCapability
    from ramalio.resources.ports import PortReservationStore

    reg = CapabilityRegistry.with_capabilities(
        [PortsCapability(port_probe=lambda p: True)]
    )
    InitWorkspaceService(cfg, registry=reg).run("feat-portreuse")

    store = PortReservationStore(cfg.repository_root)
    before = store.load("feat-portreuse")
    assert before is not None

    from ramalio.core.startstop import StartWorkspaceService

    StartWorkspaceService(cfg, registry=reg).run("feat-portreuse")
    after = store.load("feat-portreuse")
    # Same port: start reused the init-time reservation instead of reallocating.
    assert after is not None and after.port == before.port



# --- P1 (E7-S0): rollback never stops a runtime that was already running ---


def test_start_rollback_does_not_stop_preexisting_runtime(
    project: Path, write_config, state_home: Path
) -> None:
    """If the runtime was already running before `start`, a later capability
    failure must NOT stop it: ownership is about what THIS start created, not
    the resulting state (E7-S0 R3/R11)."""

    from ramalio.capabilities.runtime import RuntimeCapability
    from ramalio.capabilities.runtime.base import RuntimeResult, RuntimeState

    write_config(
        project,
        _BASE_CONFIG + '\n[capabilities.runtime]\nenabled = true\ndriver = "fake-p1"\n',
    )
    cfg = resolve_project_config(project)

    calls: list[str] = []

    class _FakeDriver:
        name = "fake-p1"

        def start(self, ws):
            calls.append("start")
            return RuntimeResult(RuntimeState.RUNNING, "running (already up)")

        def stop(self, ws):
            calls.append("stop")
            return RuntimeResult(RuntimeState.STOPPED, "stopped")

        def doctor(self, ws):
            return ()

        def status(self, ws):
            calls.append("status")
            return RuntimeResult(RuntimeState.RUNNING, "running")

        def cleanup(self, ws):
            return RuntimeResult(RuntimeState.STOPPED, "cleaned")

    runtime_cap = RuntimeCapability(drivers={"fake-p1": lambda o, ctx=None: _FakeDriver()})

    class _FailAfterStart:
        capability_name = "failer"

        @property
        def name(self):
            return self.capability_name

        def is_enabled(self, ctx):
            return True

        def handle(self, event, context):
            if event == "after_start":
                raise RuntimeError("boom after runtime started")
            return None

        def compensate(self, event, context):
            pass

        def validate_config(self, ctx):
            return None

        def status(self, ctx):
            raise NotImplementedError

        def doctor_checks(self, ctx):
            return ()

    InitWorkspaceService(
        cfg, registry=CapabilityRegistry.with_capabilities([runtime_cap])
    ).run("feat-p1")

    from ramalio.core.startstop import StartWorkspaceService

    start_reg = CapabilityRegistry.with_capabilities([runtime_cap, _FailAfterStart()])
    with pytest.raises(Exception):
        StartWorkspaceService(cfg, registry=start_reg).run("feat-p1")

    assert "stop" not in calls, "rollback must not stop a preexisting runtime"



# --- P5 (E7-S0 R3/R11): init never releases a preexisting port reservation -


def test_init_rollback_does_not_release_preexisting_port(
    project: Path, write_config, state_home: Path
) -> None:
    """A port reservation that already existed before `init` (e.g. leftover
    from an earlier partial run for the same target) must never be released
    by a rollback triggered by a later capability failure."""

    write_config(
        project, _BASE_CONFIG + "\n[ports]\nenabled = true\nstart = 8600\nsize = 5\n"
    )
    cfg = resolve_project_config(project)
    from ramalio.capabilities.ports_capability import PortsCapability
    from ramalio.resources.ports import PortAllocator, PortReservationStore

    ports_cap = PortsCapability(port_probe=lambda p: True)

    # Pre-existing reservation, as if left over from an earlier partial run.
    store = PortReservationStore(cfg.repository_root)
    preexisting = PortAllocator(cfg.ports, store, port_probe=lambda p: True).reserve(
        "feat-p5"
    )

    class _FailAfterInit:
        capability_name = "failer"

        @property
        def name(self):
            return self.capability_name

        def is_enabled(self, ctx):
            return True

        def handle(self, event, context):
            if event == "after_init":
                raise RuntimeError("boom after init")
            return None

        def compensate(self, event, context):
            pass

        def validate_config(self, ctx):
            return None

        def status(self, ctx):
            raise NotImplementedError

        def doctor_checks(self, ctx):
            return ()

    reg = CapabilityRegistry.with_capabilities([ports_cap, _FailAfterInit()])
    with pytest.raises(Exception):
        InitWorkspaceService(cfg, registry=reg).run("feat-p5")

    after = store.load("feat-p5")
    assert after is not None and after.port == preexisting.port



# --- P10 (E7-S0): resources_started counts real mutations, not no-ops ------


def test_start_reports_no_op_when_nothing_changed(
    project: Path, write_config, state_home: Path
) -> None:
    """When `start` finds every resource already in place (e.g. the port
    reserved at init), it must report resources_started == 0 and no_op == True,
    not count a changed=False HookResult as a started resource (P10)."""

    write_config(
        project, _BASE_CONFIG + "\n[ports]\nenabled = true\nstart = 8700\nsize = 5\n"
    )
    cfg = resolve_project_config(project)
    from ramalio.capabilities.ports_capability import PortsCapability
    from ramalio.core.startstop import StartWorkspaceService

    reg = CapabilityRegistry.with_capabilities(
        [PortsCapability(port_probe=lambda p: True)]
    )
    # init reserves the port; the subsequent start must reuse it (no change).
    InitWorkspaceService(cfg, registry=reg).run("feat-noop")

    outcome = StartWorkspaceService(cfg, registry=reg).run("feat-noop")
    assert outcome.resources_started == 0
    assert outcome.no_op is True
