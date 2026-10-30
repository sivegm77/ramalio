"""Optional tunnel capability and provider contract (E6-S3)."""

from __future__ import annotations

from .base import (
    LocalEndpoint,
    TunnelDoctorCheck,
    TunnelProvider,
    TunnelResult,
    TunnelState,
    TunnelWorkspace,
)
from .capability import CAPABILITY_NAME, TunnelCapability, register_provider
from .zrok import PROVIDER_NAME as ZROK_PROVIDER, ZrokProvider

__all__ = [
    "CAPABILITY_NAME",
    "LocalEndpoint",
    "TunnelCapability",
    "TunnelDoctorCheck",
    "TunnelProvider",
    "TunnelResult",
    "TunnelState",
    "TunnelWorkspace",
    "ZROK_PROVIDER",
    "ZrokProvider",
    "register_provider",
]
