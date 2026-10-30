"""Runtime driver contract (E6-S0).

A *runtime* is an optional per-target resource lifecycle (containers, services,
...).  The contract is driver-agnostic: no Docker-specific decision appears here
(R9/INV).  The base behavior is the ``none`` driver; concrete drivers (e.g.
Docker Compose in E6-S2) plug in without changing the contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from ...core.naming import ResolvedWorkspaceIdentity


class RuntimeState(Enum):
    """Minimal runtime state vocabulary (R4)."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class RuntimeScope(Enum):
    """Where a runtime command executes (E10-S1 R2).

    ``PROJECT`` targets the shared base runtime derived from the repository root
    and ``base_project_pattern`` (``workspace`` is ``None``).  ``WORKSPACE``
    targets the per-target runtime derived from the worktree and
    ``project_pattern`` (``workspace`` is required).
    """

    PROJECT = "project"
    WORKSPACE = "workspace"


@dataclass(frozen=True, slots=True)
class RuntimeWorkspace:
    """The workspace a runtime driver operates on."""

    target: str
    worktree_path: Path
    identity: ResolvedWorkspaceIdentity
    # Repository root lets a driver resolve project-scoped external resources
    # (e.g. the E6-S1 port reservation) without coupling the contract to them.
    repository_root: Path | None = None


@dataclass(frozen=True, slots=True)
class RuntimeResult:
    """Structured result of a runtime operation.

    ``changed`` is the driver's *authoritative* statement of whether THIS call
    actually mutated the runtime (E7-S0 R3/R11, audit H3/H6): the driver is the
    only component that truly knows whether ``docker compose up`` brought
    something up or merely found it already running.  When a driver leaves it
    ``None`` (it cannot tell), the capability must fall back to a fail-closed
    heuristic rather than assuming a mutation happened.
    """

    state: RuntimeState
    summary: str
    details: str | None = None
    changed: bool | None = None


@dataclass(frozen=True, slots=True)
class RuntimeDoctorCheck:
    """A diagnostic check contributed by a runtime driver (R8)."""

    check_id: str
    ok: bool
    summary: str
    details: str | None = None


@runtime_checkable
class RuntimeDriver(Protocol):
    """The runtime driver contract (R2).

    All operations are idempotent from the contract's perspective (R6).
    """

    @property
    def name(self) -> str:
        ...

    def doctor(self, workspace: RuntimeWorkspace | None) -> tuple[RuntimeDoctorCheck, ...]:
        ...

    def start(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        ...

    def provision(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        """Prepare/bring up the runtime so the workspace is usable during
        provisioning (E10-S1 R1).

        Distinct from :meth:`start`, which keeps normal resume semantics.  A
        driver that manages no runtime returns a NOT_APPLICABLE no-op.
        """
        ...

    def stop(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        ...

    def status(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        ...

    def cleanup(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        ...


@dataclass(frozen=True, slots=True)
class RuntimeExecRequest:
    """A structured request to run argv inside a runtime service (E10-S1 R2).

    Every field is explicit so nothing is shell-tokenized: ``argv`` is a tuple
    of tokens, ``env`` is an explicit mapping, and ``workdir`` is a path *inside*
    the runtime (never a host path).  ``stdin`` streams bytes to the process
    (used by data providers that pipe a dump into a restore).
    """

    service: str
    argv: tuple[str, ...]
    env: Mapping[str, str] = field(default_factory=dict)
    user: str | None = None
    workdir: str | None = None
    stdin: bytes | None = None

    def __post_init__(self) -> None:
        if not self.service or not self.service.strip():
            raise ValueError("RuntimeExecRequest.service must be a non-empty string")
        if not self.argv:
            raise ValueError("RuntimeExecRequest.argv must not be empty")
        if any((not tok or not isinstance(tok, str)) for tok in self.argv):
            raise ValueError(
                "RuntimeExecRequest.argv must contain only non-empty strings"
            )


@dataclass(frozen=True, slots=True)
class RuntimeExecResult:
    """Result of a runtime command execution (E10-S1 R2).

    Carries the process ``returncode`` and raw ``stdout``/``stderr`` bytes.  It
    never prints automatically; the caller decides what to surface.
    """

    returncode: int
    stdout: bytes
    stderr: bytes


@runtime_checkable
class RuntimeCommandExecutor(Protocol):
    """Optional seam for drivers that can run argv inside a runtime (E10-S1 R2).

    Not every driver implements this: only providers that need to execute
    commands inside a running service (E10-S2 runtime executor, E10-S3 Postgres
    provider) require it.  Downstream providers depend on this protocol, not on
    Docker Compose, so they never import the concrete driver.
    """

    def ensure_service(
        self,
        scope: RuntimeScope,
        workspace: RuntimeWorkspace | None,
        service: str,
    ) -> RuntimeResult:
        """Ensure ``service`` is running in the requested ``scope``."""
        ...

    def exec(
        self,
        scope: RuntimeScope,
        workspace: RuntimeWorkspace | None,
        request: RuntimeExecRequest,
    ) -> RuntimeExecResult:
        """Execute ``request`` inside the runtime service for ``scope``."""
        ...
