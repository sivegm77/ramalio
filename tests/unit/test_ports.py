"""Tests for per-target port allocation and lifecycle integration (E6-S1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import CapabilityContext, CapabilityRegistry
from ramalio.capabilities.ports_capability import PortsCapability
from ramalio.config.loader import resolve_project_config
from ramalio.config.target import build_workspace_naming
from ramalio.core.errors import (
    PortRangeExhaustedError,
    ProjectConfigInvalidError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.target import Target
from ramalio.resources.ports import PortAllocator, PortReservationStore


def _config_body(ports: str = "") -> str:
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
{ports}
"""


# --- config validation (R2) ------------------------------------------------


def test_ports_range_validation(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body("\n[ports]\nenabled = true\nstart = 70000\nsize = 5\n"),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_ports_size_validation(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        _config_body("\n[ports]\nenabled = true\nstart = 8100\nsize = 0\n"),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_ports_disabled_default(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, _config_body())
    config = resolve_project_config(git_repo_with_commit)
    assert config.ports.enabled is False


# --- allocator (R3/R5/R6/R7/R11/R12) ---------------------------------------


def _allocator(tmp_path: Path, *, start=8100, size=20, free_all=True):
    from ramalio.config.models import PortsConfig

    store = PortReservationStore(tmp_path / "repo", base=tmp_path / "state")
    probe = (lambda port: True) if free_all else (lambda port: False)
    return PortAllocator(
        PortsConfig(enabled=True, start=start, size=size), store, port_probe=probe
    ), store


def test_ac02_first_target_gets_port(tmp_path: Path) -> None:
    allocator, _ = _allocator(tmp_path)
    reservation = allocator.reserve("alpha")
    assert 8100 <= reservation.port <= 8119


def test_ac03_second_target_no_collision(tmp_path: Path) -> None:
    allocator, _ = _allocator(tmp_path)
    a = allocator.reserve("alpha")
    b = allocator.reserve("bravo")
    assert a.port != b.port


def test_ac04_same_target_keeps_port(tmp_path: Path) -> None:
    allocator, _ = _allocator(tmp_path)
    first = allocator.reserve("alpha")
    second = allocator.reserve("alpha")
    assert first.port == second.port  # R11 idempotent


def test_deterministic_candidate(tmp_path: Path) -> None:
    a1, _ = _allocator(tmp_path)
    a2, _ = _allocator(tmp_path / "other")
    # Same target -> same preferred candidate order (deterministic, R3).
    assert a1._candidates("alpha") == a2._candidates("alpha")


def test_ac05_external_occupied_skipped(tmp_path: Path) -> None:
    from ramalio.config.models import PortsConfig

    store = PortReservationStore(tmp_path / "repo", base=tmp_path / "state")
    # First candidate for 'alpha' is occupied; everything else free.
    allocator_probe = PortAllocator(
        PortsConfig(enabled=True, start=8100, size=20), store
    )
    preferred = allocator_probe._candidates("alpha")[0]

    def probe(port: int) -> bool:
        return port != preferred

    allocator = PortAllocator(
        PortsConfig(enabled=True, start=8100, size=20), store, port_probe=probe
    )
    reservation = allocator.reserve("alpha")
    assert reservation.port != preferred


def test_ac06_range_exhausted(tmp_path: Path) -> None:
    allocator, _ = _allocator(tmp_path, start=8100, size=1)
    allocator.reserve("alpha")  # takes the only port
    with pytest.raises(PortRangeExhaustedError):
        allocator.reserve("bravo")


def test_ac07_release_only_own(tmp_path: Path) -> None:
    allocator, store = _allocator(tmp_path)
    allocator.reserve("alpha")
    allocator.reserve("bravo")
    assert allocator.release("alpha") is True
    assert store.load("alpha") is None
    assert store.load("bravo") is not None  # not released


# --- lifecycle integration -------------------------------------------------


def test_ac01_init_reserves_when_enabled(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body("\n[ports]\nenabled = true\nstart = 8200\nsize = 10\n"),
    )
    registry = CapabilityRegistry.with_capabilities(
        [PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True)]
    )
    InitWorkspaceService(
        resolve_project_config(git_repo_with_commit), registry=registry
    ).run("feat-a")

    store = PortReservationStore(git_repo_with_commit, base=tmp_path / "state")
    reservation = store.load("feat-a")
    assert reservation is not None
    assert 8200 <= reservation.port <= 8209


def test_destroy_releases_reservation(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body("\n[ports]\nenabled = true\nstart = 8300\nsize = 10\n"),
    )
    registry = CapabilityRegistry.with_capabilities(
        [PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True)]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-b")
    store = PortReservationStore(git_repo_with_commit, base=tmp_path / "state")
    assert store.load("feat-b") is not None

    from ramalio.core.destroy import DestroyWorkspaceService

    DestroyWorkspaceService(cfg, registry=registry).run("feat-b")
    assert store.load("feat-b") is None


def test_ac08_status_shows_port(
    git_repo_with_commit: Path, write_config, tmp_path: Path
) -> None:
    write_config(
        git_repo_with_commit,
        _config_body("\n[ports]\nenabled = true\nstart = 8400\nsize = 10\n"),
    )
    config = resolve_project_config(git_repo_with_commit)
    cap = PortsCapability(store_base=tmp_path / "state", port_probe=lambda p: True)
    identity = build_workspace_naming(config).resolve(Target.from_trusted("feat-c"))
    ctx = CapabilityContext(config=config, identity=identity)
    # Reserve then check status.
    cap._allocator(ctx).reserve("feat-c")
    from ramalio.capabilities import CapabilityState

    assert cap.status(ctx).state == CapabilityState.ACTIVE
