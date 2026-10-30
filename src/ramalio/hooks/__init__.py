"""Lifecycle hooks connecting capabilities to init/start/stop/destroy (E4-S1).

The core commands stay authoritative for Git safety (INV-01); hooks only add
optional, sequential, deterministic capability behavior around the central Git
operation, with explicit failure and compensation semantics.
"""

from __future__ import annotations

from .events import (
    HookContext,
    HookJournal,
    HookJournalEntry,
    HookResult,
    LifecycleEvent,
)
from .runner import HookRunner

__all__ = [
    "HookContext",
    "HookJournal",
    "HookJournalEntry",
    "HookResult",
    "HookRunner",
    "LifecycleEvent",
]
