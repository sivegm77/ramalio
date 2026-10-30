"""Conformance: failure injection, concurrency, orphan detection (E7-S3).

These validate the robustness contract (rollback, locks, diagnostics) at the
conformance level, reusing the harness and fakes so no external tool is needed.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from ramalio.capabilities import BaseCapability, CapabilityRegistry
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import CapabilityHookFailedError, LockTimeoutError
from ramalio.core.init import InitWorkspaceService
from ramalio.resources.locks import LockKey, LockManager, LockScope

from .harness import PROFILE_GIT_ONLY, make_project


# --- R7/R8: failure injection after the Git workspace exists ---------------


class _FailAfterInit(BaseCapability):
    capability_name = "recorder"

    def handle(self, event: str, context: object) -> object:
        if event == "after_init":
            raise RuntimeError("injected failure")
        return None


def test_failure_after_init_rolls_back(tmp_path: Path) -> None:
    project = make_project(tmp_path, PROFILE_GIT_ONLY)
    # Enable a fake capability that fails after_init.
    (project.root / ".ramalio.toml").write_text(
        PROFILE_GIT_ONLY + "\n[capabilities.recorder]\nenabled = true\n",
        encoding="utf-8",
    )
    registry = CapabilityRegistry.with_capabilities([_FailAfterInit()])
    service = InitWorkspaceService(
        resolve_project_config(project.root), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feat-fail")

    # R8: no residual Git resources owned by the failed operation.
    repo = project.repo()
    assert not repo.branch_exists("feat-fail")
    assert repo.get_worktree_by_path(project.worktree_path("feat-fail")) is None


# --- R9: concurrency (same-target exclusion, different-target parallel) -----


def test_same_target_lock_excludes(tmp_path: Path) -> None:
    mgr = LockManager("conf", base=tmp_path / "state", timeout=0.3)
    key = LockKey(LockScope.TARGET, "feat-a")
    with mgr.acquire(key, operation="init"):
        with pytest.raises(LockTimeoutError):
            with mgr.acquire(key, operation="init", timeout=0.2):
                pass


def test_different_targets_parallel(tmp_path: Path) -> None:
    mgr = LockManager("conf", base=tmp_path / "state")
    with mgr.acquire(LockKey(LockScope.TARGET, "a"), operation="init"):
        with mgr.acquire(LockKey(LockScope.TARGET, "b"), operation="init"):
            assert True


# --- R10: port race across processes ---------------------------------------


def _reserve_port(base: str, target: str, out) -> None:
    from ramalio.config.models import PortsConfig
    from ramalio.resources.locks import LockManager
    from ramalio.resources.ports import PortAllocator, PortReservationStore

    store = PortReservationStore(Path(base) / "repo", base=Path(base) / "state")
    mgr = LockManager("conf", base=Path(base) / "state")
    allocator = PortAllocator(
        PortsConfig(enabled=True, start=8100, size=50),
        store,
        port_probe=lambda p: True,
        lock_manager=mgr,
    )
    out.put(allocator.reserve(target).port)


def test_port_race_no_duplicate(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    q = ctx.Queue()
    procs = [
        ctx.Process(target=_reserve_port, args=(str(tmp_path), f"t{i}", q))
        for i in range(6)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=10)
    ports = sorted(q.get() for _ in range(6))
    # R10: all distinct ports despite concurrent reservation.
    assert len(set(ports)) == len(ports)


# --- R12: orphan detection --------------------------------------------------


def test_orphan_process_metadata_is_stale(tmp_path: Path) -> None:
    from ramalio.capabilities import CapabilityContext
    from ramalio.capabilities.processes import ProcessesCapability, ProcessState
    from ramalio.capabilities.processes.runtime import (
        ProcessMetadata,
        ProcessMetadataStore,
    )
    from ramalio.config.target import build_workspace_naming
    from ramalio.core.target import Target

    project = make_project(tmp_path, PROFILE_GIT_ONLY)
    (project.root / ".ramalio.toml").write_text(
        PROFILE_GIT_ONLY
        + "\n[capabilities.processes]\nenabled = true\n"
        + '\n[[capabilities.processes.items]]\nname = "worker"\ncommand = ["sleep", "1"]\n',
        encoding="utf-8",
    )
    # Record an orphan (dead pid) and confirm status reports STALE.
    store = ProcessMetadataStore(project.root, "feat-orphan", base=tmp_path / "state")
    store.save(
        ProcessMetadata(
            target="feat-orphan", process_name="worker", pid=999999,
            start_time="1", cwd=".",
        )
    )
    config = resolve_project_config(project.root)
    cap = ProcessesCapability(metadata_base=tmp_path / "state")
    identity = build_workspace_naming(config).resolve(Target.from_trusted("feat-orphan"))
    ctx = CapabilityContext(config=config, identity=identity)
    statuses = {s.name: s for s in cap.item_statuses(ctx)}
    assert statuses["worker"].state == ProcessState.STALE
