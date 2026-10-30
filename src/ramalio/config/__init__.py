"""Project configuration discovery, loading, validation and precedence.

The rest of the product must consume :class:`ResolvedProjectConfig` produced by
this package rather than reading ``.ramalio.toml`` directly (R14).
"""

from __future__ import annotations

from .defaults import product_defaults
from .loader import PersonalConfigSource, load_project_config, resolve_project_config
from .models import (
    BranchConfig,
    CapabilityConfig,
    IntegrationConfig,
    ProjectConfig,
    ResolvedProjectConfig,
    TargetConfig,
    TargetNormalizationConfig,
    WorktreeConfig,
)
from .target import build_target_policy, build_target_validator

__all__ = [
    "BranchConfig",
    "CapabilityConfig",
    "IntegrationConfig",
    "PersonalConfigSource",
    "ProjectConfig",
    "ResolvedProjectConfig",
    "TargetConfig",
    "TargetNormalizationConfig",
    "WorktreeConfig",
    "build_target_policy",
    "build_target_validator",
    "load_project_config",
    "product_defaults",
    "resolve_project_config",
]
