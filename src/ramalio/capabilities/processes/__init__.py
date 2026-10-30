"""Generic managed-processes capability (E4-S2)."""

from __future__ import annotations

from .capability import CAPABILITY_NAME, ProcessesCapability
from .models import ProcessItem, ProcessState, ProcessStatus

__all__ = [
    "CAPABILITY_NAME",
    "ProcessesCapability",
    "ProcessItem",
    "ProcessState",
    "ProcessStatus",
]
