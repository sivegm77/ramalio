"""Capability contract: the stable boundary for optional behaviors (E4-S0).

A *capability* is an optional behavior a workspace may coordinate (processes,
tmux, runtime, tunnels, ...).  The core knows only this contract, never any
concrete implementation (INV-01/INV-02): no ``if tool == "tmux"`` ever leaks
into lifecycle, status or doctor.

The contract (R1) is intentionally small:

* a stable unique ``name`` (INV-04);
* ``is_enabled(context)`` derived from project configuration (INV-03);
* ``validate_config(context)`` for the capability's namespaced section (R12);
* ``status(context)`` returning a structured :class:`CapabilityStatus` (R8);
* ``doctor_checks(context)`` contributing diagnostics to ``doctor`` (R11).

Lifecycle operations (start/stop hooks) are deliberately *not* part of this
contract yet; they arrive in E4-S1 without breaking this interface.

Capabilities never load arbitrary code from TOML (INV-07): the configuration
only selects among capabilities the installation already knows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..config.models import CapabilityConfig, ResolvedProjectConfig
from ..core.naming import ResolvedWorkspaceIdentity


class CapabilityState(Enum):
    """Common capability states (R7).

    Not every capability uses every state; the enum is the shared vocabulary so
    status and tooling stay uniform across capabilities.
    """

    DISABLED = "DISABLED"
    READY = "READY"
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CapabilityStatus:
    """Structured capability status (R8)."""

    name: str
    state: CapabilityState
    summary: str
    details: str | None = None


class DoctorCheckStatus(Enum):
    """Status of a capability-contributed doctor check (R11).

    Mirrors the core doctor statuses so contributed checks aggregate uniformly
    without the doctor core knowing concrete capability names.
    """

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class CapabilityDoctorCheck:
    """A diagnostic check contributed by a capability (R11)."""

    check_id: str
    status: DoctorCheckStatus
    summary: str
    details: str | None = None
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityContext:
    """Context passed to capabilities without coupling them to the CLI (7.2).

    ``config`` is the resolved project configuration; ``identity`` and
    ``workspace_status`` are optional because doctor-level checks run without a
    concrete target while status runs for a specific workspace.
    """

    config: ResolvedProjectConfig
    identity: ResolvedWorkspaceIdentity | None = None
    # Opaque to the core; a capability may receive richer workspace status in
    # later specs.  Kept as object to avoid a premature coupling to E3-S1 types.
    workspace_status: object | None = None

    def capability_config(self, name: str) -> CapabilityConfig | None:
        """Return the ``[capabilities.<name>]`` entry, if declared."""

        return self.config.capabilities.get(name)


@runtime_checkable
class Capability(Protocol):
    """The capability contract (R1).

    Implementations are plain objects registered explicitly with the registry;
    no dynamic import or plugin discovery is involved (INV-07/R4).
    """

    @property
    def name(self) -> str:
        """Stable, unique capability identifier (INV-04)."""
        ...

    def is_enabled(self, context: CapabilityContext) -> bool:
        """Whether the capability is enabled by project configuration (R6)."""
        ...

    def validate_config(self, context: CapabilityContext) -> None:
        """Validate the capability's namespaced configuration (R12).

        Raises :class:`~ramalio.core.errors.CapabilityConfigInvalidError`
        on defects.
        """
        ...

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        """Return the capability's current status (R8)."""
        ...

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        """Return diagnostic checks contributed to ``doctor`` (R11)."""
        ...

    def handle(self, event: str, context: object) -> object:
        """Handle a lifecycle event (E4-S1 R2).

        ``event`` is a lifecycle event name; ``context`` is a hook context.
        Returns a hook result (or ``None`` for a no-op).  Capabilities need not
        implement every event (R3).
        """
        ...

    def compensate(self, event: str, context: object) -> None:
        """Undo a previously-successful hook action for ``event`` (E4-S1 R6/R14)."""
        ...


class BaseCapability:
    """Convenience base implementing the common enable/validate behavior.

    Concrete capabilities may subclass this to inherit the standard
    ``enabled=true`` semantics (R6) and a no-op config validation, overriding
    only what they need.  It is not required by the protocol.
    """

    #: Subclasses must set a stable, unique name (INV-04).
    capability_name: str = ""

    @property
    def name(self) -> str:
        if not self.capability_name:
            raise ValueError("capability_name must be set")
        return self.capability_name

    def is_enabled(self, context: CapabilityContext) -> bool:
        entry = context.capability_config(self.name)
        return entry is not None and entry.enabled

    def validate_config(self, context: CapabilityContext) -> None:  # noqa: ARG002
        """Default: nothing to validate.  Override per capability (R12)."""

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                name=self.name,
                state=CapabilityState.DISABLED,
                summary="capability disabled",
            )
        return CapabilityStatus(
            name=self.name,
            state=CapabilityState.READY,
            summary="capability enabled",
        )

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:  # noqa: ARG002
        return ()

    def handle(self, event: str, context: object) -> object:  # noqa: ARG002
        """Default: no-op for every lifecycle event (E4-S1 R3).

        Concrete capabilities override this (or the per-event convenience
        methods below) only for the events they care about.
        """

        return None

    def compensate(self, event: str, context: object) -> None:  # noqa: ARG002
        """Default: nothing to compensate (E4-S1 R6)."""
