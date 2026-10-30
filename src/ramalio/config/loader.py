"""TOML loading and precedence resolution for project configuration.

This module owns the resolution flow described in the spec (7.2):

    execution directory
          -> discover Git root
          -> load product defaults
          -> load available personal configuration
          -> load .ramalio.toml
          -> apply supported environment overrides
          -> apply explicit CLI overrides
          -> validate structure
          -> ResolvedProjectConfig

TOML is treated strictly as data (7.8): the loader never executes commands,
interpolates shell, reads secrets implicitly, follows includes or evaluates
expressions.
"""

from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

from ..core.errors import ProjectConfigNotFoundError, ProjectConfigParseError
from ..core.project import Project, discover_project
from .defaults import product_defaults
from .models import ResolvedProjectConfig
from .validation import build_resolved_config

# Environment variables that may override configuration (R10).  The mapping is
# explicit and testable; only these keys are honored.  It intentionally avoids
# repository-specific variables such as KIRO_PROJECT_ROOT.
_ENV_OVERRIDES: dict[str, tuple[str, ...]] = {
    "RAMALIO_BASE_BRANCH": ("project", "base_branch"),
    "RAMALIO_WORKTREE_DIRECTORY": ("worktree", "directory"),
}

# RAMALIO_RUNTIME_BASE_PROJECT_PATTERN (audit F2): lets a developer supply,
# from their own personal/non-versioned environment, the real identity of the
# shared base runtime their project actually uses (e.g. a developer-scoped
# Compose project name). This is NOT a SiVale-specific mechanism: the core
# still knows nothing about any project, framework or developer identifier —
# it only honors a generically-named environment variable with strictly
# higher precedence than the shared project TOML (R10), exactly like
# RAMALIO_BASE_BRANCH above.
#
# Unlike the plain path-based overrides in _ENV_OVERRIDES, this one is applied
# conditionally (see ``_capability_environment_overrides``): it only takes
# effect when `[capabilities.runtime]` is ALREADY declared by a lower-priority
# source (project TOML or personal config). Applying it unconditionally would
# create the `runtime` section out of nothing for a project that never enabled
# it, silently turning an optional capability on (INV-009) just because the
# variable happens to be exported in a developer's shell profile.
_RUNTIME_BASE_PROJECT_PATTERN_ENV = "RAMALIO_RUNTIME_BASE_PROJECT_PATTERN"

# Fields a higher-priority source must never silently change because doing so
# would alter the project's identity in an incompatible way (R10).
_IDENTITY_PATH: tuple[str, ...] = ("project", "name")


@runtime_checkable
class PersonalConfigSource(Protocol):
    """Interface for optional, non-versioned personal configuration (R11).

    Personal configuration lives outside the repository and is never required
    to use ramalio.  Implementations return a TOML-shaped mapping (or an
    empty mapping when nothing is available).  Secrets never belong here (INV-05).
    """

    def load(self, project: Project) -> Mapping[str, Any]:
        """Return personal configuration for ``project`` (possibly empty)."""


class NullPersonalConfig:
    """Default personal source that contributes nothing (R11).

    Its presence keeps the precedence chain explicit without forcing a global
    configuration file to exist.
    """

    def load(self, project: Project) -> Mapping[str, Any]:  # noqa: ARG002 - stable interface
        return {}


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base`` and return a new dict.

    Tables are merged key by key; scalars and lists are replaced.  Inputs are
    not mutated, keeping resolution deterministic (INV-07).
    """

    result = deepcopy(base)
    for key, value in override.items():
        existing = result.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            result[key] = _deep_merge(existing, value)
        else:
            result[key] = deepcopy(value)
    return result


def _set_path(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    """Set ``value`` at the nested ``path``, creating tables as needed."""

    cursor = mapping
    for key in path[:-1]:
        nested = cursor.get(key)
        if not isinstance(nested, dict):
            nested = {}
            cursor[key] = nested
        cursor = nested
    cursor[path[-1]] = value


def _read_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file, mapping failures to configuration errors (R3)."""

    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ProjectConfigParseError(f"{path}: invalid TOML syntax: {exc}") from exc
    except OSError as exc:  # pragma: no cover - defensive I/O guard
        raise ProjectConfigParseError(f"{path}: could not read file: {exc}") from exc


def load_project_config(project: Project) -> dict[str, Any]:
    """Load and parse ``.ramalio.toml`` from the resolved root (R2, R3).

    Raises :class:`ProjectConfigNotFoundError` when the file is absent.
    """

    config_path = project.config_path
    if not config_path.is_file():
        raise ProjectConfigNotFoundError(
            f"no {config_path.name} found at repository root '{project.repository_root}'"
        )
    return _read_toml(config_path)


def _environment_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    """Build the override mapping from supported environment variables (R10)."""

    overrides: dict[str, Any] = {}
    for env_key, path in _ENV_OVERRIDES.items():
        if env_key in environ:
            _set_path(overrides, path, environ[env_key])
    return overrides


def _runtime_base_project_pattern_override(
    environ: Mapping[str, str], merged_so_far: Mapping[str, Any]
) -> dict[str, Any]:
    """Conditionally override `capabilities.runtime.base_project_pattern` (F2).

    Only applies when `[capabilities.runtime]` was already declared by a
    lower-priority source (personal config or project TOML): this override
    must never be the sole reason a project's runtime capability becomes
    enabled (INV-009), and it must never invent the `runtime` section from
    nothing for a project that never opted into it.
    """

    if _RUNTIME_BASE_PROJECT_PATTERN_ENV not in environ:
        return {}
    runtime_entry = merged_so_far.get("capabilities", {}).get("runtime")
    if not isinstance(runtime_entry, dict):
        return {}
    overrides: dict[str, Any] = {}
    _set_path(
        overrides,
        ("capabilities", "runtime", "base_project_pattern"),
        environ[_RUNTIME_BASE_PROJECT_PATTERN_ENV],
    )
    return overrides


def resolve_project_config(
    start: Path | str | None = None,
    *,
    personal_source: PersonalConfigSource | None = None,
    environ: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> ResolvedProjectConfig:
    """Resolve the effective, validated configuration for a project.

    Precedence, from lowest to highest (R10):
        product defaults < personal configuration < project TOML
        < supported environment overrides < explicit CLI overrides

    One environment override (``RAMALIO_RUNTIME_BASE_PROJECT_PATTERN``, F2)
    is conditional: it only takes effect when the project TOML (or personal
    config) already declares `[capabilities.runtime]`, so a developer's
    personal environment can correct the identity of the shared base runtime
    without ever being the sole reason the capability turns on (INV-009).
    """

    project = discover_project(start)
    source = personal_source if personal_source is not None else NullPersonalConfig()
    env = os.environ if environ is None else environ

    merged = product_defaults()
    merged = _deep_merge(merged, dict(source.load(project)))
    project_toml = load_project_config(project)
    merged = _deep_merge(merged, project_toml)
    merged = _deep_merge(merged, _environment_overrides(env))
    # F2: base_project_pattern override is conditional on `runtime` already
    # being declared by a lower-priority source (see docstring); it must be
    # computed against the merge state up to this point, so it never invents
    # the `runtime` section for a project that never enabled it.
    merged = _deep_merge(merged, _runtime_base_project_pattern_override(env, merged))
    if cli_overrides:
        merged = _deep_merge(merged, dict(cli_overrides))

    # Project identity is authoritative from the project TOML; lower-priority
    # personal configuration must not redefine it silently (R10).
    if project_toml.get("project", {}).get("name") is not None:
        _set_path(merged, _IDENTITY_PATH, project_toml["project"]["name"])

    return build_resolved_config(merged, repository_root=project.repository_root)
