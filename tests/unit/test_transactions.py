"""Tests for the common lifecycle transaction and rollback (E7-S0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.capabilities import BaseCapability, CapabilityRegistry
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import CapabilityHookFailedError
from ramalio.core.init import InitWorkspaceService
from ramalio.git.repository import GitRepository
from ramalio.hooks import HookResult, LifecycleEvent
from ramalio.transactions import (
    LifecycleTransaction,
    RollbackOutcome,
)

_CONFIG = """
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

[capabilities.recorder]
enabled = true
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    write_config(git_repo_with_commit, _CONFIG)
    return git_repo_with_commit


# --- transaction unit tests ------------------------------------------------


def test_reverse_lifo_compensation() -> None:
    order: list[str] = []
    tx = LifecycleTransaction("op")
    for name in ("a", "b", "c"):
        sid = tx.record_step(
            "res", name, "create", owned=True,
            compensation=lambda n=name: order.append(n),
        )
        tx.mark_completed(sid)
    outcome = tx.rollback(RuntimeError("boom"))
    # INV-02: reverse order.
    assert order == ["c", "b", "a"]
    assert outcome.outcome == RollbackOutcome.COMPLETE
    assert isinstance(outcome.primary_error, RuntimeError)


def test_unowned_not_compensated() -> None:
    order: list[str] = []
    tx = LifecycleTransaction("op")
    sid = tx.record_step(
        "res", "owned", "create", owned=True,
        compensation=lambda: order.append("owned"),
    )
    tx.mark_completed(sid)
    sid2 = tx.record_step(
        "res", "foreign", "observe", owned=False,
        compensation=lambda: order.append("foreign"),
    )
    tx.mark_completed(sid2)
    tx.rollback(None)
    # INV-01: only owned steps compensated.
    assert order == ["owned"]


def test_incomplete_step_not_compensated() -> None:
    order: list[str] = []
    tx = LifecycleTransaction("op")
    tx.record_step(
        "res", "x", "create", owned=True, compensation=lambda: order.append("x")
    )  # never marked completed
    tx.rollback(None)
    assert order == []


def test_no_safe_compensation_is_not_safe() -> None:
    tx = LifecycleTransaction("op")
    sid = tx.record_step("res", "x", "irreversible", owned=True, compensation=None)
    tx.mark_completed(sid)
    outcome = tx.rollback(RuntimeError("boom"))
    assert outcome.outcome == RollbackOutcome.NOT_SAFE
    assert "res:x" in outcome.unsafe_resources


def test_compensation_failure_is_partial_and_preserves_cause() -> None:
    def boom() -> None:
        raise RuntimeError("compensation failed")

    tx = LifecycleTransaction("op")
    sid = tx.record_step("res", "x", "create", owned=True, compensation=boom)
    tx.mark_completed(sid)
    primary = ValueError("primary")
    outcome = tx.rollback(primary)
    # INV-04: primary error preserved; rollback errors recorded.
    assert outcome.outcome == RollbackOutcome.PARTIAL
    assert outcome.primary_error is primary
    assert outcome.rollback_errors


def test_idempotent_compensation_safe() -> None:
    calls: list[int] = []

    def comp() -> None:
        calls.append(1)

    tx = LifecycleTransaction("op")
    sid = tx.record_step("res", "x", "create", owned=True, compensation=comp)
    tx.mark_completed(sid)
    tx.rollback(None)
    tx.rollback(None)  # repeat safe (INV-06)
    assert len(calls) == 2  # each rollback ran once; compensation itself is safe


# --- init integration: capability failure rolls back Git + capability ------


class _RecorderCapability(BaseCapability):
    capability_name = "recorder"

    def __init__(self, log: list[str]) -> None:
        self._log = log

    def handle(self, event: str, context: object) -> object:
        self._log.append(event)
        if event == "after_init":
            raise RuntimeError("cap boom")
        return None


def test_ac01_init_capability_failure_reverts_git(project: Path) -> None:
    log: list[str] = []
    registry = CapabilityRegistry.with_capabilities([_RecorderCapability(log)])
    service = InitWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    with pytest.raises(CapabilityHookFailedError):
        service.run("feat-a")

    # AC-01/AC-04: the Git branch/worktree created by this init are rolled back;
    # preexisting resources untouched.
    repo = GitRepository.from_root(project)
    assert not repo.branch_exists("feat-a")
    assert repo.get_worktree_by_path(
        (project / ".local-wt" / "feat-a").resolve()
    ) is None


class _CompensatingCapability(BaseCapability):
    capability_name = "recorder"

    def __init__(self, log: list[str]) -> None:
        self._log = log

    def handle(self, event: str, context: object) -> object:
        if event == "after_init":
            self._log.append("started")
            return HookResult(
                capability=self.name,
                event=LifecycleEvent(event),
                success=True,
                changed=True,
                summary="ok",
                compensation_available=True,
            )
        return None

    def compensate(self, event: str, context: object) -> None:
        self._log.append("compensated")


def test_capability_success_then_git_ok(project: Path) -> None:
    # When after_init succeeds, no rollback happens and the workspace exists.
    log: list[str] = []
    registry = CapabilityRegistry.with_capabilities([_CompensatingCapability(log)])
    service = InitWorkspaceService(
        resolve_project_config(project), registry=registry
    )
    service.run("feat-ok")
    assert log == ["started"]
    assert GitRepository.from_root(project).branch_exists("feat-ok")
