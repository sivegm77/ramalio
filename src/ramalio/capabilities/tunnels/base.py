"""Tunnel provider contract (E6-S3).

Temporary exposure of a local endpoint, modeled as a generic capability so
providers (zrok first, others later) plug in without leaking provider knowledge
into the core (R2/R5/R16).  A tunnel belongs to one target + port (INV); the
provider receives an already-resolved local endpoint and never allocates ports
itself (R4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, runtime_checkable

from ...core.naming import ResolvedWorkspaceIdentity


class TunnelState(Enum):
    """Minimal tunnel state vocabulary (R3)."""

    DISABLED = "DISABLED"
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class LocalEndpoint:
    """A resolved local endpoint to expose (R4)."""

    host: str
    port: int


@dataclass(frozen=True, slots=True)
class TunnelWorkspace:
    """The workspace a tunnel provider operates on."""

    target: str
    worktree_path: Path
    identity: ResolvedWorkspaceIdentity
    repository_root: Path | None = None


@dataclass(frozen=True, slots=True)
class TunnelResult:
    """Structured result of a tunnel operation (R3/R11).

    ``changed`` is the provider's *authoritative* statement of whether THIS call
    actually created/tore down an exposure (E7-S0 R3/R11, audit H4): the
    provider is the only component that truly knows whether it opened a new
    tunnel or found one already active.  When a provider leaves it ``None`` (it
    cannot tell), the capability must fall back to a fail-closed heuristic rather
    than assuming a mutation happened.
    """

    state: TunnelState
    summary: str
    public_url: str | None = None
    details: str | None = None
    changed: bool | None = None


@dataclass(frozen=True, slots=True)
class TunnelDoctorCheck:
    check_id: str
    ok: bool
    summary: str
    details: str | None = None


@runtime_checkable
class TunnelProvider(Protocol):
    """The tunnel provider contract (R2)."""

    @property
    def name(self) -> str:
        ...

    def doctor(self, workspace: TunnelWorkspace | None) -> tuple[TunnelDoctorCheck, ...]:
        ...

    def start(
        self, workspace: TunnelWorkspace, endpoint: LocalEndpoint
    ) -> TunnelResult:
        ...

    def stop(self, workspace: TunnelWorkspace) -> TunnelResult:
        ...

    def status(self, workspace: TunnelWorkspace) -> TunnelResult:
        ...

    def cleanup(self, workspace: TunnelWorkspace) -> TunnelResult:
        ...
