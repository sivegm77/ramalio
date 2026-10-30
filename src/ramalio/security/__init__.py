"""Local security model: path boundaries and safe command execution (E7-S2).

Centralizes the rules every layer must follow so paths and commands never become
escape/destruction vectors: a symlink-aware path boundary policy and an
argv-only, shell=False command runner with explicit environment control.
"""

from __future__ import annotations

from .paths import (
    PathBoundaryError,
    PathBoundaryPolicy,
    SafePathResolver,
    resolve_within_directory,
)
from .process import (
    CommandSpec,
    SafeProcessRunner,
    controlled_base_env,
    redact_diagnostic,
    redact_environment,
)

__all__ = [
    "CommandSpec",
    "PathBoundaryError",
    "PathBoundaryPolicy",
    "SafePathResolver",
    "SafeProcessRunner",
    "controlled_base_env",
    "redact_diagnostic",
    "redact_environment",
    "resolve_within_directory",
]
