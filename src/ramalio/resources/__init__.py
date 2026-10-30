"""Managed, per-target resources that Git does not own (E6).

The first such resource is an optional port reservation (E6-S1).  Resources are
opt-in: a project that does not configure them carries none of this behavior.
"""

from __future__ import annotations

from .ports import (
    PortAllocator,
    PortReservation,
    PortReservationStore,
)

__all__ = [
    "PortAllocator",
    "PortReservation",
    "PortReservationStore",
]
