"""Adversarial regression tests for audit findings H1-H8 (E7-S0).

Each test reproduces a specific finding from the integral audit and asserts the
fixed, fail-closed behavior.  The two transversal principles under test are:

1. ownership must be *demonstrable*, never inferred from before/after state; and
2. every partial mutation must enter the transactional model and its diagnosis.

The tests use real temporary Git repositories (H1/H2) and fake
drivers/providers (H3/H4/H6) so the ownership/rollback decisions are exercised
directly, without any real Docker/tmux/zrok.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import (
    BaseCapability,
    CapabilityContext,
    CapabilityRegistry,
)
from ramalio.capabilities.runtime.base import (
    RuntimeResult,
    RuntimeState,
)
from ramalio.capabilities.tunnels.base import TunnelResult, TunnelState
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.errors import (
    AdoptGitOperationFailedError,
    GitCommandError,
    InitRollbackIncompleteError,
    LifecycleRollbackIncompleteError,
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


def _identity(project_root: Path, target: str) -> ResolvedWorkspaceIdentity:
    config = resolve_project_config(project_root)
    return build_workspace_naming(config).resolve(Target.from_trusted(target))


# ---------------------------------------------------------------------------
# H1 — init rollback must NOT delete a worktree whose ownership it cannot prove
# ---------------------------------------------------------------------------


def test_h1_rollback_preserves_detached_worktree_at_derived_path(
    project: Path, run_git
) -> None:
    """A detached worktree that appears at the derived path during a partial
    ``init`` is NOT owned by that init.  ``_undo_worktree`` must preserve it and
    raise ``InitRollbackIncompleteError`` rather than force-remove it (H1)."""

    resolved_path = (project / ".local-wt" / "feat-h1").resolve()
    # Simulate a foreign/detached worktree sitting at the derived path.
    run_git(
        project,
        "worktree",
        "add",
        "--detach",
        str(resolved_path),
        "HEAD",
    )

    config = resolve_project_config(project)
    service = InitWorkspaceService(config)
    identity = _identity(project, "feat-h1")

    with pytest.raises(InitRollbackIncompleteError) as exc:
        service._undo_worktree(identity, resolved_path)

    # The finding: the detached worktree must still be there afterwards.
    assert "ownership not demonstrable" in str(exc.value)
    repo = GitRepository.from_root(project)
    still_there = repo.get_worktree_by_path(resolved_path)
    assert still_there is not None, "detached worktree was wrongly removed"


def test_h1_rollback_preserves_worktree_on_other_branch(
    project: Path, run_git
) -> None:
    """A worktree on a *different* branch at the derived path is also not owned
    and must be preserved (existing behavior, kept fail-closed)."""

    resolved_path = (project / ".local-wt" / "feat-h1b").resolve()
    run_git(project, "worktree", "add", "-b", "someone-else", str(resolved_path))

    config = resolve_project_config(project)
    service = InitWorkspaceService(config)
    identity = _identity(project, "feat-h1b")

    with pytest.raises(InitRollbackIncompleteError):
        service._undo_worktree(identity, resolved_path)

    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(resolved_path) is not None


# ---------------------------------------------------------------------------
# H2 — adopt must handle a ``git worktree add`` that mutates and then fails
# ---------------------------------------------------------------------------


class _MutateThenFailWriter(GitWriter):
    """Writer whose ``add_worktree_for_branch`` really attaches the worktree and
    THEN raises, modeling a Git operation that mutated before exiting non-zero."""

    def add_worktree_for_branch(self, *, branch: str, worktree_path: Path) -> None:
        # Actually create the worktree (durable mutation)...
        super().add_worktree_for_branch(branch=branch, worktree_path=worktree_path)
        # ...then fail as if Git exited non-zero after the mutation.
        raise GitCommandError(
            "simulated post-mutation failure", args=("worktree", "add")
        )


def test_h2_adopt_retires_worktree_created_despite_git_failure(
    project: Path, run_git
) -> None:
    """When ``git worktree add`` mutates and then fails during adopt, the
    worktree it created must be rolled back (ownership is demonstrable: it is on
    the target's branch) while the preexisting branch is preserved (H2)."""

    from ramalio.core.adopt import AdoptWorkspaceService

    # A preexisting branch with no worktree -> branch-only adoption path.
    run_git(project, "branch", "feat-h2", "main")

    config = resolve_project_config(project)
    writer = _MutateThenFailWriter(project)
    service = AdoptWorkspaceService(config, writer=writer)

    with pytest.raises(AdoptGitOperationFailedError):
        service.run("feat-h2")

    repo = GitRepository.from_root(project)
    resolved_path = (project / ".local-wt" / "feat-h2").resolve()
    # The worktree adopt created is retired...
    assert repo.get_worktree_by_path(resolved_path) is None
    # ...and the preexisting branch is preserved (never part of rollback).
    assert repo.branch_exists("feat-h2")


# ---------------------------------------------------------------------------
# Fakes for H3/H4/H6 (runtime + tunnel) driven through the real lifecycle
# ---------------------------------------------------------------------------


class _FakeRuntimeDriver:
    """A runtime driver whose status() is UNKNOWN (unreliable) and whose start()
    is idempotent over a preexisting runtime.  Records every call."""

    def __init__(self, calls: list[str], *, declare_changed: bool | None) -> None:
        self._calls = calls
        self._declare_changed = declare_changed

    @property
    def name(self) -> str:
        return "fake"

    def doctor(self, workspace):
        return ()

    def status(self, workspace):
        from ramalio.core.errors import RuntimeStartFailedError

        # Unreliable status: cannot tell -> the capability sees UNKNOWN.
        raise RuntimeStartFailedError("status unavailable")

    def start(self, workspace):
        self._calls.append("start")
        # Idempotent start over a preexisting runtime.
        return RuntimeResult(
            RuntimeState.RUNNING, "already running", changed=self._declare_changed
        )

    def stop(self, workspace):
        self._calls.append("stop")
        return RuntimeResult(RuntimeState.STOPPED, "stopped")

    def cleanup(self, workspace):
        self._calls.append("cleanup")
        return RuntimeResult(RuntimeState.STOPPED, "down")


class _LateFailCapability(BaseCapability):
    """A capability that fails on after_start, AFTER runtime/tunnel already ran,
    to trigger a LIFO rollback that would (wrongly) compensate them."""

    def __init__(self, name: str = "latefail") -> None:
        self.capability_name = name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return context.capability_config(self.name) is not None

    def handle(self, event: str, context: object) -> object:
        if event == "after_start":
            raise RuntimeError("boom after start (late)")
        return None


def _runtime_config(extra: str) -> str:
    return _CONFIG_BODY + extra


# ---------------------------------------------------------------------------
# H3 — runtime must NOT be stopped on rollback when status was UNKNOWN
# ---------------------------------------------------------------------------


def test_h3_runtime_not_stopped_when_status_unknown_and_not_owned(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _runtime_config(
            '\n[capabilities.runtime]\ndriver = "fake"\n'
            "\n[capabilities.latefail]\nenabled = true\n"
        ),
    )
    from ramalio.core.startstop import StartWorkspaceService

    calls: list[str] = []
    # declare_changed=None -> driver cannot tell; capability must fail closed
    # because the pre-start status was UNKNOWN (not observably STOPPED).
    driver = _FakeRuntimeDriver(calls, declare_changed=None)
    from ramalio.capabilities.runtime.capability import RuntimeCapability

    runtime = RuntimeCapability(drivers={"fake": lambda _o, _c=None: driver})
    latefail = _LateFailCapability()
    registry = CapabilityRegistry.with_capabilities([runtime, latefail])

    cfg = resolve_project_config(git_repo_with_commit)
    # Set up a READY workspace; latefail is a benign no-op on init (it only
    # raises on after_start), so init under the same registry is safe.
    InitWorkspaceService(cfg, registry=registry).run("feat-h3")
    calls.clear()

    with pytest.raises(Exception):
        StartWorkspaceService(cfg, registry=registry).run("feat-h3")

    assert "start" in calls, "runtime start should have been attempted"
    assert "stop" not in calls, (
        "runtime with UNKNOWN prior state must NOT be stopped on rollback "
        "(ownership not demonstrable)"
    )


def test_h3_runtime_stopped_when_driver_declares_it_started(
    git_repo_with_commit: Path, write_config
) -> None:
    """When the driver authoritatively declares changed=True, the runtime this
    call started IS owned and must be compensated on rollback."""

    write_config(
        git_repo_with_commit,
        _runtime_config(
            '\n[capabilities.runtime]\ndriver = "fake"\n'
            "\n[capabilities.latefail]\nenabled = true\n"
        ),
    )
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.core.startstop import StartWorkspaceService

    calls: list[str] = []
    driver = _FakeRuntimeDriver(calls, declare_changed=True)
    registry = CapabilityRegistry.with_capabilities(
        [
            RuntimeCapability(drivers={"fake": lambda _o, _c=None: driver}),
            _LateFailCapability(),
        ]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-h3b")
    calls.clear()

    with pytest.raises(Exception):
        StartWorkspaceService(cfg, registry=registry).run("feat-h3b")

    assert calls == ["start", "stop"], (
        "a runtime the driver reported it started must be compensated"
    )


# ---------------------------------------------------------------------------
# H4 — tunnel must NOT be stopped on rollback when status was UNKNOWN
# ---------------------------------------------------------------------------


class _FakeTunnelProvider:
    def __init__(self, calls: list[str], *, declare_changed: bool | None) -> None:
        self._calls = calls
        self._declare_changed = declare_changed

    @property
    def name(self) -> str:
        return "faketun"

    def doctor(self, workspace):
        return ()

    def status(self, workspace):
        from ramalio.core.errors import TunnelStartFailedError

        raise TunnelStartFailedError("status unavailable")

    def start(self, workspace, endpoint):
        self._calls.append("start")
        return TunnelResult(
            TunnelState.ACTIVE,
            "already active",
            "https://x.example",
            changed=self._declare_changed,
        )

    def stop(self, workspace):
        self._calls.append("stop")
        return TunnelResult(TunnelState.STOPPED, "stopped")

    def cleanup(self, workspace):
        self._calls.append("cleanup")
        return TunnelResult(TunnelState.STOPPED, "cleaned")


def _tunnel_config() -> str:
    return _CONFIG_BODY + (
        "\n[ports]\nenabled = true\nstart = 8600\nsize = 5\n"
        '\n[capabilities.tunnel]\nenabled = true\nprovider = "faketun"\n'
        "\n[capabilities.latefail]\nenabled = true\n"
    )


def test_h4_tunnel_not_stopped_when_status_unknown_and_not_owned(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(git_repo_with_commit, _tunnel_config())
    from ramalio.capabilities.ports_capability import PortsCapability
    from ramalio.capabilities.tunnels import TunnelCapability
    from ramalio.core.startstop import StartWorkspaceService

    calls: list[str] = []
    provider = _FakeTunnelProvider(calls, declare_changed=None)

    def _make_registry() -> CapabilityRegistry:
        return CapabilityRegistry.with_capabilities(
            [
                PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True),
                TunnelCapability(
                    providers={"faketun": lambda o: provider},
                    store_base=tmp_path / "state",
                ),
                _LateFailCapability(),
            ]
        )

    registry = _make_registry()
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-h4")
    calls.clear()

    with pytest.raises(Exception):
        StartWorkspaceService(cfg, registry=registry).run("feat-h4")

    assert "start" in calls
    assert "stop" not in calls, (
        "tunnel with UNKNOWN prior state must NOT be stopped on rollback"
    )


# ---------------------------------------------------------------------------
# H5 — stop must count resources changed in before_stop
# ---------------------------------------------------------------------------


class _StopChangingCapability(BaseCapability):
    """A capability that reports a real change on before_stop (like the built-in
    teardown capabilities do), and nothing on after_stop."""

    def __init__(self, name: str = "stopper") -> None:
        self.capability_name = name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return context.capability_config(self.name) is not None

    def handle(self, event: str, context: object) -> object:
        from ramalio.hooks import HookResult, LifecycleEvent

        if event == "before_stop":
            return HookResult(
                capability=self.capability_name,
                event=LifecycleEvent(event),
                success=True,
                changed=True,
                summary="stopped one resource",
                compensation_available=False,
            )
        return None


def test_h5_stop_counts_before_stop_changes(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _CONFIG_BODY + "\n[capabilities.stopper]\nenabled = true\n",
    )
    from ramalio.core.startstop import StopWorkspaceService

    registry = CapabilityRegistry.with_capabilities([_StopChangingCapability()])
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-h5")

    outcome = StopWorkspaceService(cfg, registry=registry).run("feat-h5")

    assert outcome.resources_stopped == 1, (
        "stop must count resources changed in before_stop, not only after_stop"
    )
    assert outcome.no_op is False


# ---------------------------------------------------------------------------
# H6 — a no-op runtime stop must not be recorded as an unsafe mutation
# ---------------------------------------------------------------------------


class _NoopStopDriver:
    """Driver already stopped: stop() is a genuine no-op and declares it."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    @property
    def name(self) -> str:
        return "fake"

    def doctor(self, workspace):
        return ()

    def status(self, workspace):
        return RuntimeResult(RuntimeState.STOPPED, "stopped")

    def start(self, workspace):
        return RuntimeResult(RuntimeState.RUNNING, "up", changed=True)

    def stop(self, workspace):
        self._calls.append("stop")
        # Already stopped -> nothing changed.
        return RuntimeResult(RuntimeState.STOPPED, "already stopped", changed=False)

    def cleanup(self, workspace):
        return RuntimeResult(RuntimeState.STOPPED, "down", changed=False)


class _FailBeforeStopCapability(BaseCapability):
    def __init__(self, name: str = "failstop") -> None:
        self.capability_name = name

    def is_enabled(self, context: CapabilityContext) -> bool:
        return context.capability_config(self.name) is not None

    def handle(self, event: str, context: object) -> object:
        if event == "before_stop":
            raise RuntimeError("boom before stop")
        return None


def test_h6_noop_runtime_stop_not_flagged_unsafe(
    git_repo_with_commit: Path, write_config
) -> None:
    """A runtime that was already stopped performs a no-op stop; when a later
    before_stop capability fails, the runtime must NOT appear as an unsafe
    rollback resource, because nothing was mutated (H6)."""

    write_config(
        git_repo_with_commit,
        _runtime_config(
            '\n[capabilities.runtime]\ndriver = "fake"\n'
            "\n[capabilities.failstop]\nenabled = true\n"
        ),
    )
    from ramalio.capabilities.runtime.capability import RuntimeCapability
    from ramalio.core.startstop import StopWorkspaceService

    calls: list[str] = []
    driver = _NoopStopDriver(calls)
    # Runtime registered before failstop so runtime.before_stop runs first
    # (no-op), then failstop.before_stop raises. Teardown order is reversed by
    # the runner, so register runtime last to make it run first on teardown.
    registry = CapabilityRegistry.with_capabilities(
        [_FailBeforeStopCapability(), RuntimeCapability(drivers={"fake": lambda _o, _c=None: driver})]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-h6")

    from ramalio.core.errors import CapabilityHookFailedError

    # The before_stop failure propagates.  The key assertion (H6): because the
    # runtime stop was a genuine no-op (changed=False), it is NOT recorded as a
    # transaction step, so rollback stays clean and the failure surfaces as the
    # plain hook failure — never escalated to LIFECYCLE_ROLLBACK_INCOMPLETE with
    # the runtime among the unsafe resources.
    with pytest.raises(BaseException) as exc:
        StopWorkspaceService(cfg, registry=registry).run("feat-h6")

    assert not isinstance(exc.value, LifecycleRollbackIncompleteError), (
        "a no-op runtime stop must not escalate the failure to an unsafe "
        "rollback"
    )
    assert isinstance(exc.value, CapabilityHookFailedError)
    # runtime.stop() ran first (teardown order) and was a declared no-op.
    assert calls == ["stop"]


# ---------------------------------------------------------------------------
# H7.A — zrok _pid_terminated must be fail-closed on an unreadable live PID
# ---------------------------------------------------------------------------


def test_h7a_pid_terminated_fail_closed_on_unreadable_live_pid(monkeypatch) -> None:
    import ramalio.capabilities.tunnels.zrok as zrok_mod

    # A PID that reports alive but whose /proc/<pid>/stat cannot be read.
    monkeypatch.setattr(zrok_mod, "_pid_alive", lambda pid: True)

    def _raise_oserror(*_a, **_k):
        raise OSError("cannot read")

    monkeypatch.setattr(zrok_mod.Path, "read_text", _raise_oserror)

    # Live but unverifiable -> must NOT be reported as terminated (fail closed).
    assert zrok_mod._pid_terminated(4242) is False


# ---------------------------------------------------------------------------
# H8 — a partial process start rollback is structurally diagnosable
# ---------------------------------------------------------------------------


def test_h8_partial_process_start_rollback_is_structured() -> None:
    """When a launch fails and the internal cleanup of already-started items
    also fails, the error must be a structured
    ``ProcessStartRollbackIncompleteError`` carrying the primary cause, the
    per-item cleanup errors and the leftover processes (H8)."""

    from ramalio.capabilities.processes.capability import ProcessesCapability
    from ramalio.capabilities.processes.models import ProcessItem
    from ramalio.capabilities.processes.runtime import (
        ProcessMetadata,
        ProcessMetadataStore,
    )
    from ramalio.core.errors import (
        ProcessOperationFailedError,
        ProcessStartRollbackIncompleteError,
    )

    # Fake identity/context minimal surface used by _start_items.
    class _Identity:
        def __init__(self) -> None:
            self.target = type("T", (), {"value": "feat-h8"})()
            from pathlib import PurePosixPath

            self.worktree_path = PurePosixPath(".local-wt") / "feat-h8"

    calls = {"launched": 0}

    class _Launcher:
        def __init__(self, worktree) -> None:
            pass

        def launch(self, item):
            calls["launched"] += 1
            if calls["launched"] == 1:
                # First item launches "successfully".
                return ProcessMetadata(
                    target="feat-h8",
                    process_name=item.name,
                    pid=4242,
                    start_time="1",
                    cwd="/tmp",
                )
            # Second item fails to launch -> triggers cleanup of the first.
            raise ProcessOperationFailedError("launch failed for second item")

    class _FailingTerminator:
        def terminate(self, metadata, *, timeout):
            # Cleanup of the already-started item ALSO fails.
            raise ProcessOperationFailedError("cannot stop already-started item")

    # Build the capability and patch its internals to use our fakes.
    cap = ProcessesCapability()

    class _Store:
        def load(self, name):
            return ProcessMetadata(
                target="feat-h8", process_name=name, pid=4242,
                start_time="1", cwd="/tmp",
            )

        def save(self, metadata):
            pass

        def delete(self, name):
            pass

    class _Inspector:
        def owns(self, metadata):
            return False  # never "already active"

    cap._inspector = _Inspector()
    cap._terminator = _FailingTerminator()
    cap._store = lambda ctx, target: _Store()  # type: ignore[assignment]
    cap._worktree_path = lambda ctx, identity: Path("/tmp")  # type: ignore[assignment]

    import ramalio.capabilities.processes.capability as cap_mod

    # Redirect ProcessLauncher used inside _start_items to our fake.
    original_launcher = cap_mod.ProcessLauncher
    cap_mod.ProcessLauncher = _Launcher  # type: ignore[assignment]
    try:
        items = [
            ProcessItem(
                name="a",
                command=("true",),
                cwd=".",
                start_on_init=True,
                start_on_start=False,
                stop_on_stop=True,
                stop_on_destroy=True,
                stop_timeout=1.0,
            ),
            ProcessItem(
                name="b",
                command=("true",),
                cwd=".",
                start_on_init=True,
                start_on_start=False,
                stop_on_stop=True,
                stop_on_destroy=True,
                stop_timeout=1.0,
            ),
        ]

        class _Ctx:
            pass

        with pytest.raises(ProcessStartRollbackIncompleteError) as exc:
            cap._start_items(_Ctx(), _Identity(), items)

        err = exc.value
        assert err.primary_error is not None
        assert err.cleanup_errors, "per-item cleanup errors must be recorded"
        assert "a" in err.leftover_processes, "leftover process must be tracked"
        # Stable exit-code mapping via OperationError.
        assert err.code == "PROCESS_START_ROLLBACK_INCOMPLETE"
    finally:
        cap_mod.ProcessLauncher = original_launcher  # type: ignore[assignment]
