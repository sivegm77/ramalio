"""Tests for the tunnel capability and zrok provider (E6-S3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ramalio.capabilities import CapabilityContext, CapabilityRegistry, CapabilityState
from ramalio.capabilities.tunnels import (
    LocalEndpoint,
    TunnelCapability,
    TunnelState,
)
from ramalio.capabilities.tunnels.zrok import (
    TunnelStateStore,
    ZrokProvider,
)
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.init import InitWorkspaceService
from ramalio.core.target import Target


def _config_body(extra: str = "") -> str:
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

[ports]
enabled = true
start = 8500
size = 10
{extra}
"""


def _ctx(project_root: Path, target: str = "feat-a") -> CapabilityContext:
    config = resolve_project_config(project_root)
    identity = build_workspace_naming(config).resolve(Target.from_trusted(target))
    return CapabilityContext(config=config, identity=identity)


# --- zrok provider with a fake launcher ------------------------------------


def _fake_launcher(url: str):
    # Launch a real short-lived process so pid-alive checks pass, and return a
    # fixed public URL.
    import subprocess

    def launcher(argv, cwd):
        proc = subprocess.Popen(["sleep", "5"], stdin=subprocess.DEVNULL)
        return proc.pid, url

    return launcher


def test_zrok_start_status_stop(tmp_path: Path) -> None:
    from ramalio.capabilities.tunnels.base import TunnelWorkspace
    from ramalio.core.naming import ResolvedWorkspaceIdentity
    from pathlib import PurePosixPath

    provider = ZrokProvider(
        state_base=tmp_path / "state",
        launcher=_fake_launcher("https://abc.zrok.io"),
    )
    wt = tmp_path / "wt"
    wt.mkdir()
    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted("feat-a"),
        branch_name="feat-a",
        worktree_path=PurePosixPath(".local-wt") / "feat-a",
    )
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=wt, identity=identity, repository_root=tmp_path
    )
    result = provider.start(ws, LocalEndpoint("127.0.0.1", 8500))
    try:
        assert result.state == TunnelState.ACTIVE
        assert result.public_url == "https://abc.zrok.io"
        # AC-07: status exposes public URL.
        status = provider.status(ws)
        assert status.state == TunnelState.ACTIVE
        assert status.public_url == "https://abc.zrok.io"
    finally:
        stop = provider.stop(ws)
        assert stop.state == TunnelState.STOPPED
        assert provider.status(ws).state == TunnelState.STOPPED


def test_ac04_two_targets_distinct_state(tmp_path: Path) -> None:
    store = TunnelStateStore(tmp_path / "repo", base=tmp_path / "state")
    from ramalio.capabilities.tunnels.zrok import TunnelRecord

    store.save(TunnelRecord("alpha", pid=111, public_url="a"))
    store.save(TunnelRecord("bravo", pid=222, public_url="b"))
    assert store.load("alpha").public_url == "a"
    assert store.load("bravo").public_url == "b"


# --- capability lifecycle + endpoint from reserved port --------------------


class _FakeProvider:
    def __init__(self, options=None) -> None:
        self.started_endpoint = None
        self.stopped = False

    @property
    def name(self) -> str:
        return "fake"

    def doctor(self, workspace):
        from ramalio.capabilities.tunnels.base import TunnelDoctorCheck

        return (TunnelDoctorCheck("TUNNEL_FAKE", True, "fake ready"),)

    def start(self, workspace, endpoint):
        from ramalio.capabilities.tunnels.base import TunnelResult

        self.started_endpoint = endpoint
        return TunnelResult(TunnelState.ACTIVE, "started", "https://fake.example")

    def stop(self, workspace):
        from ramalio.capabilities.tunnels.base import TunnelResult

        self.stopped = True
        return TunnelResult(TunnelState.STOPPED, "stopped")

    def status(self, workspace):
        from ramalio.capabilities.tunnels.base import TunnelResult

        return TunnelResult(TunnelState.STOPPED, "stopped")

    def cleanup(self, workspace):
        return self.stop(workspace)


def test_ac03_start_uses_reserved_port(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.tunnel]\nenabled = true\nprovider = "fake"\n'),
    )
    provider = _FakeProvider()
    from ramalio.capabilities.ports_capability import PortsCapability

    tunnel = TunnelCapability(
        providers={"fake": lambda o: provider}, store_base=tmp_path / "state"
    )
    ports = PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True)
    # Ports registered before tunnel so the reservation exists at after_start.
    registry = CapabilityRegistry.with_capabilities([ports, tunnel])
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-a")

    from ramalio.core.startstop import StartWorkspaceService

    StartWorkspaceService(cfg, registry=registry).run("feat-a")
    assert provider.started_endpoint is not None
    assert 8500 <= provider.started_endpoint.port <= 8509


def test_ac06_destroy_cleans_tunnel(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.tunnel]\nenabled = true\nprovider = "fake"\n'),
    )
    provider = _FakeProvider()
    from ramalio.capabilities.ports_capability import PortsCapability

    registry = CapabilityRegistry.with_capabilities(
        [
            PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True),
            TunnelCapability(
                providers={"fake": lambda o: provider}, store_base=tmp_path / "state"
            ),
        ]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-b")

    from ramalio.core.destroy import DestroyWorkspaceService

    DestroyWorkspaceService(cfg, registry=registry).run("feat-b")
    assert provider.stopped is True


# --- AC-01/AC-02: disabled needs nothing; doctor detects missing zrok ------


def test_ac01_disabled_no_provider_needed(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(git_repo_with_commit, _config_body())  # tunnel not configured
    cap = TunnelCapability()
    assert cap.status(_ctx(git_repo_with_commit)).state == CapabilityState.DISABLED
    assert cap.doctor_checks(_ctx(git_repo_with_commit)) == ()


def test_ac02_doctor_detects_missing_zrok(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body('\n[capabilities.tunnel]\nenabled = true\nprovider = "zrok"\n'),
    )
    ctx = _ctx(git_repo_with_commit)
    # Inject a zrok provider pointing at a non-existent executable so the
    # availability check fails without disturbing the shared shutil.
    provider = ZrokProvider(executable="zrok-nonexistent-binary-xyz")
    cap = TunnelCapability(providers={"zrok": lambda o: provider})
    checks = cap.doctor_checks(ctx)
    zrok = [c for c in checks if c.check_id == "ZROK_AVAILABLE"]
    from ramalio.capabilities.base import DoctorCheckStatus

    assert zrok and zrok[0].status == DoctorCheckStatus.FAIL


# --- AC-09: another provider registers without touching lifecycle ----------


def test_ac09_custom_provider_registers() -> None:
    from ramalio.capabilities.tunnels.capability import (
        _PROVIDERS,
        register_provider,
    )

    register_provider("custom-x", lambda o: _FakeProvider())
    assert "custom-x" in _PROVIDERS
    assert "zrok" in _PROVIDERS


# --- AC-08: secrets never printed ------------------------------------------


def test_ac08_no_secret_in_status(tmp_path: Path, monkeypatch) -> None:
    # The provider only ever surfaces the public URL, never tokens; ensure a
    # token in the environment does not leak into any result string.
    monkeypatch.setenv("ZROK_TOKEN", "super-secret-token")
    provider = ZrokProvider(
        state_base=tmp_path / "state", launcher=_fake_launcher("https://x.zrok.io")
    )
    from ramalio.capabilities.tunnels.base import TunnelWorkspace
    from ramalio.core.naming import ResolvedWorkspaceIdentity
    from pathlib import PurePosixPath

    wt = tmp_path / "wt"
    wt.mkdir()
    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted("feat-a"),
        branch_name="feat-a",
        worktree_path=PurePosixPath(".local-wt") / "feat-a",
    )
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=wt, identity=identity, repository_root=tmp_path
    )
    result = provider.start(ws, LocalEndpoint("127.0.0.1", 8500))
    try:
        assert "super-secret-token" not in (result.summary or "")
        assert "super-secret-token" not in (result.public_url or "")
    finally:
        provider.stop(ws)



# --- H4 (E6-S3 R7/R8/R9): zrok fails closed without ownership fingerprint ---


def test_zrok_start_fails_closed_without_fingerprint_support(
    tmp_path: Path, monkeypatch
) -> None:
    """When this platform cannot provide the ownership fingerprint (no /proc,
    e.g. macOS), start() must refuse instead of launching an unmanageable
    tunnel that status would immediately report FAILED."""

    import ramalio.capabilities.tunnels.zrok as zrok_mod
    from ramalio.core.errors import TunnelStartFailedError

    monkeypatch.setattr(
        zrok_mod, "_ownership_fingerprint_supported", lambda: False
    )

    launched: list[object] = []

    def fake_launcher(argv, cwd):
        launched.append(argv)
        return (12345, None)

    from ramalio.capabilities.tunnels.base import TunnelWorkspace

    provider = zrok_mod.ZrokProvider(state_base=tmp_path, launcher=fake_launcher)
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=tmp_path, identity=None, repository_root=tmp_path
    )

    with pytest.raises(TunnelStartFailedError):
        provider.start(ws, LocalEndpoint(host="127.0.0.1", port=8100))

    # The launcher was never invoked: start failed BEFORE launching anything.
    assert launched == []



# --- P7 (E6-S3 R7/R8): start fails closed if no fingerprint after launch ---


def test_zrok_start_fails_when_fingerprint_missing_after_launch(tmp_path: Path) -> None:
    """If the process cannot be fingerprinted right after launch (e.g. it exited
    instantly or the PID is unreadable), start() must fail closed and NOT
    persist an unmanageable tunnel record that status would report FAILED."""

    from ramalio.capabilities.tunnels.base import TunnelWorkspace
    from ramalio.capabilities.tunnels.zrok import TunnelStateStore
    from ramalio.core.errors import TunnelStartFailedError

    # Launcher returns a PID that does not exist -> no fingerprint capturable.
    def bad_launcher(argv, cwd):
        return (999999, "https://x.zrok.io")

    provider = ZrokProvider(state_base=tmp_path / "state", launcher=bad_launcher)
    ws = TunnelWorkspace(
        target="feat-a", worktree_path=tmp_path, identity=None, repository_root=tmp_path
    )
    with pytest.raises(TunnelStartFailedError):
        provider.start(ws, LocalEndpoint("127.0.0.1", 8500))

    # No tunnel state was persisted.
    store = TunnelStateStore(tmp_path, base=tmp_path / "state")
    assert store.load("feat-a") is None


# --- P8 (E6-S3 R10): stop verifies termination before clearing state -------


def test_zrok_stop_fails_if_process_survives(tmp_path: Path) -> None:
    """If the owned process does not terminate within the timeout, stop() must
    NOT delete the ownership record (so the tunnel stays diagnosable) and must
    report a stop failure rather than a false STOPPED."""

    import subprocess

    from ramalio.capabilities.tunnels.base import TunnelWorkspace
    from ramalio.capabilities.tunnels.zrok import (
        TunnelStateStore,
        _read_start_time,
    )
    from ramalio.core.errors import TunnelStopFailedError

    # A process that ignores SIGTERM so it survives the stop timeout.
    proc = subprocess.Popen(
        ["sh", "-c", "trap '' TERM; sleep 30"], stdin=subprocess.DEVNULL
    )
    try:
        import time as _time

        _time.sleep(0.1)
        store = TunnelStateStore(tmp_path, base=tmp_path / "state")
        from ramalio.capabilities.tunnels.zrok import TunnelRecord

        store.save(
            TunnelRecord(
                target="feat-a",
                pid=proc.pid,
                public_url="https://x.zrok.io",
                start_time=_read_start_time(proc.pid),
            )
        )
        provider = ZrokProvider(state_base=tmp_path / "state", stop_timeout=0.3)
        ws = TunnelWorkspace(
            target="feat-a",
            worktree_path=tmp_path,
            identity=None,
            repository_root=tmp_path,
        )
        with pytest.raises(TunnelStopFailedError):
            provider.stop(ws)
        # Ownership record preserved for diagnosis/retry.
        assert store.load("feat-a") is not None
    finally:
        proc.kill()
        proc.wait(timeout=2)
