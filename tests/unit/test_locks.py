"""Tests for granular cross-process locks and concurrency (E7-S1)."""

from __future__ import annotations

import multiprocessing
import time
from pathlib import Path

import pytest

from ramalio.core.errors import LockTimeoutError
from ramalio.resources.locks import LockKey, LockManager, LockScope


def _manager(tmp_path: Path, timeout: float = 1.0) -> LockManager:
    return LockManager("proj", base=tmp_path / "state", timeout=timeout)


# --- basic acquire/release -------------------------------------------------


def test_acquire_release(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    key = LockKey(LockScope.TARGET, "feat-a")
    with mgr.acquire(key, operation="init") as info:
        assert info.operation == "init"
        assert mgr.is_held_by_live_process(key) is True
    # Released after the context.
    assert mgr.is_held_by_live_process(key) is False


def test_released_on_exception(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    key = LockKey(LockScope.TARGET, "feat-b")
    with pytest.raises(RuntimeError):
        with mgr.acquire(key, operation="init"):
            raise RuntimeError("boom")
    # AC-05: released even on exception.
    assert mgr.is_held_by_live_process(key) is False


# --- distinct scopes/values do not block -----------------------------------


def test_distinct_targets_parallel(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    a = LockKey(LockScope.TARGET, "alpha")
    b = LockKey(LockScope.TARGET, "bravo")
    # AC-02: two distinct targets acquire simultaneously.
    with mgr.acquire(a, operation="init"):
        with mgr.acquire(b, operation="init"):
            assert True


# --- deterministic multi-lock order ----------------------------------------


def test_acquire_all_ordered(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    keys = [
        LockKey(LockScope.PORT_POOL, "pool"),
        LockKey(LockScope.TARGET, "t"),
        LockKey(LockScope.PROJECT, "p"),
    ]
    with mgr.acquire_all(keys, operation="init") as infos:
        scopes = [i.scope for i in infos]
        # Sorted by scope value: PROJECT < TARGET < PORT_POOL.
        assert scopes == ["PROJECT", "TARGET", "PORT_POOL"]


# --- timeout ----------------------------------------------------------------


def _hold_lock(base: str, ready, release) -> None:
    mgr = LockManager("proj", base=Path(base))
    key = LockKey(LockScope.TARGET, "contended")
    with mgr.acquire(key, operation="hold"):
        ready.set()
        release.wait(timeout=5)


def test_ac04_timeout_when_held_by_other_process(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    proc = ctx.Process(
        target=_hold_lock, args=(str(tmp_path / "state"), ready, release)
    )
    proc.start()
    try:
        assert ready.wait(timeout=5)
        mgr = _manager(tmp_path, timeout=0.3)
        key = LockKey(LockScope.TARGET, "contended")
        # AC-04: contended lock times out with a clear error.
        with pytest.raises(LockTimeoutError):
            with mgr.acquire(key, operation="init"):
                pass
    finally:
        release.set()
        proc.join(timeout=5)


# --- stale recovery (owner process gone) -----------------------------------


def test_ac06_stale_recovered_after_owner_exits(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Event()
    release = ctx.Event()
    proc = ctx.Process(
        target=_hold_lock, args=(str(tmp_path / "state"), ready, release)
    )
    proc.start()
    assert ready.wait(timeout=5)
    key = LockKey(LockScope.TARGET, "contended")
    mgr = _manager(tmp_path, timeout=0.3)
    assert mgr.is_held_by_live_process(key) is True
    # Owner exits -> OS releases the flock -> lock is recoverable safely (R11).
    release.set()
    proc.join(timeout=5)
    # Now acquirable without any manual stale removal.
    with mgr.acquire(key, operation="init", timeout=2.0):
        assert True


# --- diagnostics (R16) ------------------------------------------------------


def test_lock_info_readable(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    key = LockKey(LockScope.TARGET, "feat-x")
    with mgr.acquire(key, operation="destroy"):
        info = mgr.read_lock_info(key)
        assert info is not None
        assert info.operation == "destroy"
        assert info.pid > 0


# --- port allocation lock ---------------------------------------------------


def test_ac03_port_lock_serializes_reservation(tmp_path: Path) -> None:
    from ramalio.config.models import PortsConfig
    from ramalio.resources.ports import PortAllocator, PortReservationStore

    store = PortReservationStore(tmp_path / "repo", base=tmp_path / "state")
    mgr = _manager(tmp_path)
    allocator = PortAllocator(
        PortsConfig(enabled=True, start=8100, size=20),
        store,
        port_probe=lambda p: True,
        lock_manager=mgr,
    )
    a = allocator.reserve("alpha")
    b = allocator.reserve("bravo")
    # Distinct ports even though both go through the pool lock.
    assert a.port != b.port


# --- lifecycle: same target serialized (AC-01) -----------------------------


def test_ac01_same_target_init_serialized(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    from ramalio.config.loader import resolve_project_config
    from ramalio.core.errors import WorkspaceAlreadyExistsError
    from ramalio.core.init import InitWorkspaceService

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
    mgr = _manager(tmp_path, timeout=5.0)
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, lock_manager=mgr).run("feat-a")
    # Second init of the same target fails controlled (idempotency), and the
    # lock was released after the first (no deadlock).
    with pytest.raises(WorkspaceAlreadyExistsError):
        InitWorkspaceService(cfg, lock_manager=mgr).run("feat-a")
