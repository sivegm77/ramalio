"""Tests for the managed-processes capability (E4-S2).

Uses real, short-lived temporary processes (sleep) and a temporary metadata
directory.  Covers ownership, start/stop, idempotency, PID-reuse protection,
status, doctor and lifecycle integration (AC-01..AC-10).
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from ramalio.capabilities import (
    CapabilityContext,
    CapabilityRegistry,
    CapabilityState,
)
from ramalio.capabilities.processes import ProcessesCapability, ProcessState
from ramalio.capabilities.processes.models import parse_process_items
from ramalio.capabilities.processes.runtime import (
    ProcessMetadata,
    ProcessMetadataStore,
)
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.errors import (
    CapabilityHookFailedError,
    ProcessDuplicateNameError,
)
from ramalio.core.destroy import DestroyWorkspaceService
from ramalio.core.init import InitWorkspaceService
from ramalio.core.startstop import (
    StartWorkspaceService,
    StopWorkspaceService,
)


def _config_body(items: str, extra: str = "") -> str:
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

[capabilities.processes]
enabled = true
{items}
{extra}
"""


_TWO_ITEMS = """
[[capabilities.processes.items]]
name = "svc-a"
command = ["sleep", "30"]
start_on_start = true
stop_on_stop = true

[[capabilities.processes.items]]
name = "svc-b"
command = ["sleep", "30"]
start_on_start = true
stop_on_stop = true
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _config_body(_TWO_ITEMS))
    return git_repo_with_commit


@pytest.fixture
def meta_base(tmp_path: Path) -> Path:
    return tmp_path / "state"


def _registry(meta_base: Path) -> CapabilityRegistry:
    return CapabilityRegistry.with_capabilities(
        [ProcessesCapability(metadata_base=meta_base)]
    )


def _identity(project_root: Path, target: str):
    config = resolve_project_config(project_root)
    return build_workspace_naming(config).resolve(
        __import__(
            "ramalio.core.target", fromlist=["Target"]
        ).Target.from_trusted(target)
    )


def _capctx(project_root: Path, target: str) -> CapabilityContext:
    config = resolve_project_config(project_root)
    return CapabilityContext(config=config, identity=_identity(project_root, target))


# --- config parsing (AC-01) ------------------------------------------------


def test_ac01_two_processes_declared(project: Path) -> None:
    config = resolve_project_config(project)
    entry = config.capabilities["processes"]
    items = parse_process_items(entry.options)
    assert [i.name for i in items] == ["svc-a", "svc-b"]
    assert items[0].command == ("sleep", "30")


def test_duplicate_name_rejected(git_repo_with_commit: Path, write_config) -> None:
    dup = """
[[capabilities.processes.items]]
name = "dup"
command = ["sleep", "1"]

[[capabilities.processes.items]]
name = "dup"
command = ["sleep", "1"]
"""
    write_config(git_repo_with_commit, _config_body(dup))
    config = resolve_project_config(git_repo_with_commit)
    with pytest.raises(ProcessDuplicateNameError):
        parse_process_items(config.capabilities["processes"].options)


def test_shell_string_command_rejected(
    git_repo_with_commit: Path, write_config
) -> None:
    bad = """
[[capabilities.processes.items]]
name = "x"
command = "sleep 30"
"""
    write_config(git_repo_with_commit, _config_body(bad))
    config = resolve_project_config(git_repo_with_commit)
    from ramalio.core.errors import CapabilityConfigInvalidError

    with pytest.raises(CapabilityConfigInvalidError):
        parse_process_items(config.capabilities["processes"].options)


# --- start / stop / status via lifecycle (AC-02, AC-03, AC-04, AC-06) ------


def _make_workspace(project: Path, target: str) -> None:
    InitWorkspaceService(resolve_project_config(project)).run(target)


def test_ac02_start_launches_and_ac06_status_active(
    project: Path, meta_base: Path
) -> None:
    _make_workspace(project, "feat-a")
    registry = _registry(meta_base)
    StartWorkspaceService(resolve_project_config(project), registry=registry).run(
        "feat-a"
    )
    try:
        cap = ProcessesCapability(metadata_base=meta_base)
        statuses = {s.name: s for s in cap.item_statuses(_capctx(project, "feat-a"))}
        assert statuses["svc-a"].state == ProcessState.ACTIVE
        assert statuses["svc-b"].state == ProcessState.ACTIVE
    finally:
        StopWorkspaceService(
            resolve_project_config(project), registry=registry
        ).run("feat-a")


def test_ac03_second_start_does_not_duplicate(project: Path, meta_base: Path) -> None:
    _make_workspace(project, "feat-dup")
    registry = _registry(meta_base)
    start = StartWorkspaceService(resolve_project_config(project), registry=registry)
    start.run("feat-dup")
    cap = ProcessesCapability(metadata_base=meta_base)
    pid_first = {
        s.name: s.pid for s in cap.item_statuses(_capctx(project, "feat-dup"))
    }
    try:
        start.run("feat-dup")  # second start
        pid_second = {
            s.name: s.pid for s in cap.item_statuses(_capctx(project, "feat-dup"))
        }
        assert pid_first == pid_second  # not duplicated
    finally:
        StopWorkspaceService(
            resolve_project_config(project), registry=registry
        ).run("feat-dup")


def test_ac04_stop_terminates_owned_process(project: Path, meta_base: Path) -> None:
    _make_workspace(project, "feat-stop")
    registry = _registry(meta_base)
    StartWorkspaceService(resolve_project_config(project), registry=registry).run(
        "feat-stop"
    )
    cap = ProcessesCapability(metadata_base=meta_base)
    pids = [s.pid for s in cap.item_statuses(_capctx(project, "feat-stop"))]

    StopWorkspaceService(resolve_project_config(project), registry=registry).run(
        "feat-stop"
    )
    # Give the OS a moment.
    time.sleep(0.2)
    statuses = cap.item_statuses(_capctx(project, "feat-stop"))
    assert all(s.state == ProcessState.STOPPED for s in statuses)
    for pid in pids:
        assert pid is not None
        # Process must be gone.
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


# --- AC-05: PID reuse protection -------------------------------------------


def test_ac05_pid_reuse_not_terminated(project: Path, meta_base: Path) -> None:
    from ramalio.capabilities.processes.runtime import (
        ProcessInspector,
        ProcessTerminator,
    )
    from ramalio.core.errors import ProcessOwnershipMismatchError

    # Write metadata with a start_time fingerprint that will not match the
    # current process at that PID (simulate reuse using our own PID).
    store = ProcessMetadataStore(project, "feat-reuse", base=meta_base)
    fake = ProcessMetadata(
        target="feat-reuse",
        process_name="svc-a",
        pid=os.getpid(),
        start_time="0",  # deliberately wrong fingerprint
        cwd=".",
    )
    store.save(fake)

    terminator = ProcessTerminator(ProcessInspector())
    with pytest.raises(ProcessOwnershipMismatchError):
        terminator.terminate(fake, timeout=1.0)


# --- AC-06: STALE status ----------------------------------------------------


def test_ac06_stale_status(project: Path, meta_base: Path) -> None:
    store = ProcessMetadataStore(project, "feat-stale", base=meta_base)
    store.save(
        ProcessMetadata(
            target="feat-stale",
            process_name="svc-a",
            pid=999999,  # unlikely to exist
            start_time="123",
            cwd=".",
        )
    )
    cap = ProcessesCapability(metadata_base=meta_base)
    statuses = {s.name: s for s in cap.item_statuses(_capctx(project, "feat-stale"))}
    assert statuses["svc-a"].state == ProcessState.STALE


# --- AC-07: destroy blocks if required process cannot be stopped safely ----


def test_ac07_destroy_blocks_on_ownership_mismatch(
    project: Path, meta_base: Path
) -> None:
    _make_workspace(project, "feat-block")
    # Record metadata for a required stop_on_destroy process pointing at a live
    # PID with a wrong fingerprint -> ownership mismatch -> destroy blocked.
    store = ProcessMetadataStore(project, "feat-block", base=meta_base)
    store.save(
        ProcessMetadata(
            target="feat-block",
            process_name="svc-a",
            pid=os.getpid(),
            start_time="0",
            cwd=".",
        )
    )
    registry = _registry(meta_base)
    service = DestroyWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feat-block")

    # Worktree preserved because before_destroy blocked.
    from ramalio.git.repository import GitRepository

    repo = GitRepository.from_root(project)
    assert repo.get_worktree_by_path(
        (project / ".local-wt" / "feat-block").resolve()
    ) is not None


# --- AC-08: doctor validates command availability --------------------------


def test_ac08_doctor_checks_command(git_repo_with_commit: Path, write_config) -> None:
    body = _config_body(
        """
[[capabilities.processes.items]]
name = "ghost"
command = ["this-command-does-not-exist-xyz"]
"""
    )
    write_config(git_repo_with_commit, body)
    from ramalio.core.doctor import CheckStatus, DoctorService

    registry = CapabilityRegistry.with_capabilities([ProcessesCapability()])
    report = DoctorService(start=git_repo_with_commit, registry=registry).run()
    ghost = [r for r in report.results if r.check_id == "PROCESS_GHOST_COMMAND"]
    assert ghost and ghost[0].status == CheckStatus.WARN


def test_ac08_doctor_command_available(git_repo_with_commit: Path, write_config) -> None:
    body = _config_body(
        """
[[capabilities.processes.items]]
name = "sleeper"
command = ["sleep", "1"]
"""
    )
    write_config(git_repo_with_commit, body)
    from ramalio.core.doctor import CheckStatus, DoctorService

    registry = CapabilityRegistry.with_capabilities([ProcessesCapability()])
    report = DoctorService(start=git_repo_with_commit, registry=registry).run()
    sleeper = [r for r in report.results if r.check_id == "PROCESS_SLEEPER_COMMAND"]
    assert sleeper and sleeper[0].status == CheckStatus.PASS


# --- AC-10: partial start failure compensates only started processes -------


def test_ac10_partial_start_compensation(
    git_repo_with_commit: Path, write_config, meta_base: Path
) -> None:
    # svc-good starts; svc-bad fails to launch (missing executable). The started
    # svc-good must be compensated (stopped) so no orphan remains.
    body = _config_body(
        """
[[capabilities.processes.items]]
name = "svc-good"
command = ["sleep", "30"]
start_on_start = true

[[capabilities.processes.items]]
name = "svc-bad"
command = ["definitely-not-a-real-binary-xyz"]
start_on_start = true
"""
    )
    write_config(git_repo_with_commit, body)
    _make_workspace(git_repo_with_commit, "feat-partial")
    registry = _registry(meta_base)
    service = StartWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feat-partial")

    # svc-good was started then compensated (stopped); no active metadata.
    cap = ProcessesCapability(metadata_base=meta_base)
    ctx = CapabilityContext(
        config=resolve_project_config(git_repo_with_commit),
        identity=_identity(git_repo_with_commit, "feat-partial"),
    )
    statuses = {s.name: s for s in cap.item_statuses(ctx)}
    assert statuses["svc-good"].state == ProcessState.STOPPED



# --- P3 (E7-S0 R3/R11): rollback never stops a preexisting process ---------


def test_start_rollback_does_not_stop_preexisting_process(
    project: Path, meta_base: Path
) -> None:
    """If svc-a was already running before `start` (e.g. from a previous call),
    a later capability failure must stop only svc-b (started by THIS call),
    never svc-a: recomputing the compensation target set from configuration
    instead of the actual per-call started set would stop both."""

    from ramalio.capabilities import BaseCapability
    from ramalio.capabilities.processes.runtime import _read_start_time

    cfg = resolve_project_config(project)
    proc_cap = ProcessesCapability(metadata_base=meta_base)
    InitWorkspaceService(
        cfg, registry=CapabilityRegistry.with_capabilities([proc_cap])
    ).run("feat-a")

    # Simulate svc-a already running before this `start` call.
    import subprocess

    proc_a = subprocess.Popen(["sleep", "30"])
    time.sleep(0.1)
    store = ProcessMetadataStore(cfg.repository_root, "feat-a", base=meta_base)
    store.save(
        ProcessMetadata(
            target="feat-a",
            process_name="svc-a",
            pid=proc_a.pid,
            start_time=_read_start_time(proc_a.pid),
            cwd=str(cfg.repository_root / ".local-wt" / "feat-a"),
        )
    )

    class _FailAfterStart(BaseCapability):
        capability_name = "failer"

        def is_enabled(self, ctx):
            return True

        def handle(self, event, context):
            if event == "after_start":
                raise RuntimeError("boom after processes started")
            return None

    try:
        start_reg = CapabilityRegistry.with_capabilities(
            [proc_cap, _FailAfterStart()]
        )
        with pytest.raises(CapabilityHookFailedError):
            StartWorkspaceService(cfg, registry=start_reg).run("feat-a")

        time.sleep(0.2)
        assert proc_a.poll() is None, "preexisting svc-a must survive rollback"
        assert store.load("svc-b") is None, "svc-b started by this call must be stopped"
    finally:
        proc_a.terminate()
        try:
            proc_a.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc_a.kill()
