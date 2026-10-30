"""Optional data capability: isolated PostgreSQL data provisioning (E10-S3)."""

from __future__ import annotations

from .capability import CAPABILITY_NAME, DataCapability
from .models import DataConfig, parse_data_config

__all__ = [
    "CAPABILITY_NAME",
    "DataCapability",
    "DataConfig",
    "parse_data_config",
]
