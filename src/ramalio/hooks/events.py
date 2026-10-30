"""Lifecycle hook events, context, result and in-memory journal (E4-S1).

These are the stable contracts that connect capabilities to the fundamental
lifecycle (init/start/stop/destroy) without embedding concrete logic into the
core commands (INV-01).  The event set is fixed (R1); the hook context and
result are transport-neutral value objects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from ..capabilities.base import CapabilityContext


class LifecycleEvent(Enum):
    """The exact initial set of lifecycle events (R1)."""

    BEFORE_INIT = "before_init"
    AFTER_INIT = "after_init"
    AFTER_ADOPT = "after_adopt"
    BEFORE_START = "before_start"
    AFTER_START = "after_start"
    BEFORE_STOP = "before_stop"
    AFTER_STOP = "after_stop"
    BEFORE_DESTROY = "before_destroy"
    AFTER_DESTROY = "after_destroy"

    @property
    def is_before(self) -> bool:
        return self.value.startswith("before_")

    @property
    def is_after(self) -> bool:
        return self.value.startswith("after_")

    @property
    def is_teardown(self) -> bool:
        """Whether this event tears resources down (E6-S3 R13 ordering).

        Teardown events (stop/destroy phases) must invoke capabilities in
        reverse registration order so a tunnel is closed before the runtime it
        depends on (``stop: tunnel -> runtime``) and before the port/worktree is
        released (``destroy``: tunnel cleanup before port release).  Setup
        events (init/adopt/start phases) keep forward order so the runtime comes
        up before the tunnel (``start: runtime -> tunnel``) and provisioning
        capabilities run in registry order (E10-S0 R6).
        """

        return self in {
            LifecycleEvent.BEFORE_STOP,
            LifecycleEvent.AFTER_STOP,
            LifecycleEvent.BEFORE_DESTROY,
            LifecycleEvent.AFTER_DESTROY,
        }


@dataclass(frozen=True, slots=True)
class HookContext:
    """Context passed to a capability hook (R4).

    Wraps the capability context (project config + identity) and adds the
    operation name plus optional central-operation result data for ``after_*``
    hooks.  ``data`` is an open mapping so lifecycle operations can pass result
    facts without coupling the hook contract to their concrete types.
    """

    capability_context: CapabilityContext
    operation: str
    data: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HookResult:
    """Result of a single capability hook execution (R15)."""

    capability: str
    event: LifecycleEvent
    success: bool
    changed: bool
    summary: str
    compensation_available: bool = False


@dataclass(slots=True)
class HookJournalEntry:
    """A recorded successful, potentially compensable hook action (7.3)."""

    capability_name: str
    event: LifecycleEvent
    changed: bool
    compensation_available: bool


@dataclass(slots=True)
class HookJournal:
    """In-memory record of successful hook actions for compensation (7.3, R14).

    Not durable persistence; E7 may harden recovery.  Its sole purpose is to
    bound compensation to actions performed by the current operation, executed
    in reverse order (INV-06/R14).
    """

    entries: list[HookJournalEntry] = field(default_factory=list)

    def record(self, entry: HookJournalEntry) -> None:
        self.entries.append(entry)

    def compensable_reversed(self) -> list[HookJournalEntry]:
        """Return compensable entries in reverse order of success (R14)."""

        return [e for e in reversed(self.entries) if e.compensation_available]
