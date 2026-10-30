"""Optional bootstrap capability: dependency provisioning + readiness (E10-S2)."""

from __future__ import annotations

from .capability import CAPABILITY_NAME, BootstrapCapability
from .models import (
    ArtifactKind,
    BootstrapArtifact,
    BootstrapConfig,
    parse_bootstrap_config,
)

__all__ = [
    "CAPABILITY_NAME",
    "ArtifactKind",
    "BootstrapArtifact",
    "BootstrapCapability",
    "BootstrapConfig",
    "parse_bootstrap_config",
]
