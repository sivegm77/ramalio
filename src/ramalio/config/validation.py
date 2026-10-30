"""Structural validation of the merged configuration mapping (R12, 7.6).

Validation is fail-closed: unknown keys inside known namespaces are rejected so
typos such as ``worktree.direcotry`` never pass silently.  Validation runs on
the already-merged mapping (defaults + personal + project + overrides) and
produces the typed, immutable model.

This module performs *structural* validation only.  Target regex/example
semantics and pattern expansion belong to later specs (E1-S1, E1-S2).
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ..core.errors import ConfigVersionUnsupportedError, ProjectConfigInvalidError
from .models import (
    BranchConfig,
    CapabilityConfig,
    IntegrationConfig,
    MetaConfig,
    PortsConfig,
    ProjectConfig,
    ResolvedProjectConfig,
    TargetConfig,
    TargetNormalizationConfig,
    WorktreeConfig,
)

# Top-level sections allowed in E1.  Future namespaces cannot be invented
# without a contract change (R12 decision).
_KNOWN_TOP_LEVEL = frozenset(
    {
        "meta",
        "project",
        "target",
        "worktree",
        "branch",
        "ports",
        "capabilities",
        "integrations",
    }
)


def _fail(path: str, message: str) -> "ProjectConfigInvalidError":
    """Build a diagnostic invalid-config error pointing at ``path``."""

    return ProjectConfigInvalidError(f"{path}: {message}")


def _require_table(value: Any, path: str) -> Mapping[str, Any]:
    """Ensure ``value`` is a TOML table (mapping)."""

    if not isinstance(value, dict):
        raise _fail(path, f"expected a table, got {type(value).__name__}")
    return value


def _reject_unknown_keys(table: Mapping[str, Any], allowed: frozenset[str], path: str) -> None:
    """Reject keys not present in ``allowed`` (fail-closed, R12)."""

    unknown = sorted(set(table) - allowed)
    if unknown:
        joined = ", ".join(unknown)
        raise _fail(path, f"unknown key(s): {joined}")


def _require_non_empty_str(value: Any, path: str) -> str:
    """Ensure ``value`` is a non-empty string scalar."""

    if isinstance(value, bool) or not isinstance(value, str):
        raise _fail(path, f"expected a non-empty string, got {type(value).__name__}")
    if value.strip() == "":
        raise _fail(path, "expected a non-empty string, got an empty value")
    return value


def _require_str(value: Any, path: str) -> str:
    """Ensure ``value`` is a string scalar (may be empty)."""

    if isinstance(value, bool) or not isinstance(value, str):
        raise _fail(path, f"expected a string, got {type(value).__name__}")
    return value


def _require_bool(value: Any, path: str) -> bool:
    """Ensure ``value`` is a boolean scalar."""

    if not isinstance(value, bool):
        raise _fail(path, f"expected a boolean, got {type(value).__name__}")
    return value


def _require_non_negative_int(value: Any, path: str) -> int:
    """Ensure ``value`` is a non-negative integer scalar."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(path, f"expected an integer, got {type(value).__name__}")
    if value < 0:
        raise _fail(path, f"expected a non-negative integer, got {value}")
    return value


def _optional_str(table: Mapping[str, Any], key: str, path: str) -> str | None:
    """Return an optional string field or ``None`` when absent."""

    if key not in table:
        return None
    return _require_str(table[key], f"{path}.{key}")


def _build_meta(table: Mapping[str, Any]) -> MetaConfig:
    from .. import SUPPORTED_CONFIG_SCHEMA

    _reject_unknown_keys(table, frozenset({"schema_version"}), "meta")
    raw = table.get("schema_version", SUPPORTED_CONFIG_SCHEMA)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise _fail("meta.schema_version", "must be an integer")
    if raw < 1:
        raise _fail("meta.schema_version", "must be >= 1")
    # Fail-closed: a newer-than-supported schema is never interpreted (R12/R17).
    if raw > SUPPORTED_CONFIG_SCHEMA:
        raise ConfigVersionUnsupportedError(
            f"configuration requires schema version {raw}, but this CLI supports "
            f"up to {SUPPORTED_CONFIG_SCHEMA}; upgrade ramalio"
        )
    return MetaConfig(schema_version=raw)


def _build_project(table: Mapping[str, Any]) -> ProjectConfig:
    _reject_unknown_keys(table, frozenset({"name", "base_branch"}), "project")
    if "name" not in table:
        raise _fail("project.name", "is required")
    name = _require_non_empty_str(table["name"], "project.name")
    if "base_branch" not in table:
        raise _fail("project.base_branch", "is required")
    base_branch = _require_non_empty_str(table["base_branch"], "project.base_branch")
    return ProjectConfig(name=name, base_branch=base_branch)


def _build_target_normalization(table: Mapping[str, Any]) -> TargetNormalizationConfig:
    path = "target.normalization"
    _reject_unknown_keys(
        table,
        frozenset(
            {
                "trim",
                "lowercase_slug",
                "replace_spaces",
                "collapse_dashes",
                "slug_separator",
                "preserve_prefix_segments",
            }
        ),
        path,
    )
    return TargetNormalizationConfig(
        trim=_require_bool(table["trim"], f"{path}.trim"),
        lowercase_slug=_require_bool(table["lowercase_slug"], f"{path}.lowercase_slug"),
        replace_spaces=_require_str(table["replace_spaces"], f"{path}.replace_spaces"),
        collapse_dashes=_require_bool(table["collapse_dashes"], f"{path}.collapse_dashes"),
        slug_separator=_require_non_empty_str(
            table["slug_separator"], f"{path}.slug_separator"
        ),
        preserve_prefix_segments=_require_non_negative_int(
            table["preserve_prefix_segments"], f"{path}.preserve_prefix_segments"
        ),
    )


def _build_target(table: Mapping[str, Any]) -> TargetConfig:
    _reject_unknown_keys(
        table,
        frozenset({"regex", "example", "case_sensitive", "normalization"}),
        "target",
    )
    normalization_table = _require_table(
        table.get("normalization", {}), "target.normalization"
    )
    return TargetConfig(
        regex=_optional_str(table, "regex", "target"),
        example=_optional_str(table, "example", "target"),
        case_sensitive=_require_bool(
            table.get("case_sensitive", False), "target.case_sensitive"
        ),
        normalization=_build_target_normalization(normalization_table),
    )


def _build_worktree(table: Mapping[str, Any]) -> WorktreeConfig:
    _reject_unknown_keys(table, frozenset({"directory", "pattern"}), "worktree")
    return WorktreeConfig(
        directory=_require_non_empty_str(table["directory"], "worktree.directory"),
        pattern=_require_non_empty_str(table["pattern"], "worktree.pattern"),
    )


def _build_branch(table: Mapping[str, Any]) -> BranchConfig:
    _reject_unknown_keys(
        table, frozenset({"pattern", "delete_on_destroy"}), "branch"
    )
    return BranchConfig(
        pattern=_require_non_empty_str(table["pattern"], "branch.pattern"),
        delete_on_destroy=_require_bool(
            table.get("delete_on_destroy", False), "branch.delete_on_destroy"
        ),
    )


def _build_ports(table: Mapping[str, Any]) -> PortsConfig:
    _reject_unknown_keys(table, frozenset({"enabled", "start", "size"}), "ports")
    enabled = _require_bool(table.get("enabled", False), "ports.enabled")
    start = table.get("start", 8100)
    size = table.get("size", 20)
    if isinstance(start, bool) or not isinstance(start, int):
        raise _fail("ports.start", "must be an integer")
    if isinstance(size, bool) or not isinstance(size, int):
        raise _fail("ports.size", "must be an integer")
    # Fail-fast validation of the range (E6-S1 R2).
    if not (1 <= start <= 65535):
        raise _fail("ports.start", "must be between 1 and 65535")
    if size <= 0:
        raise _fail("ports.size", "must be greater than 0")
    if start + size - 1 > 65535:
        raise _fail("ports", "range end exceeds 65535")
    return PortsConfig(enabled=enabled, start=start, size=size)


def _build_capabilities(table: Mapping[str, Any]) -> Mapping[str, CapabilityConfig]:
    capabilities: dict[str, CapabilityConfig] = {}
    for name, raw in table.items():
        path = f"capabilities.{name}"
        entry = _require_table(raw, path)
        enabled = _require_bool(entry.get("enabled", False), f"{path}.enabled")
        options = {key: value for key, value in entry.items() if key != "enabled"}
        capabilities[name] = CapabilityConfig(
            name=name,
            enabled=enabled,
            options=MappingProxyType(dict(options)),
        )
    return MappingProxyType(capabilities)


# Public keys an ``[integrations.<name>]`` table may declare (E9-S3 INV-01).
# Fail-closed: any other key (e.g. the retired ``inherit_env``, E9-S3 R8/INV-05)
# is rejected as an unsupported option so a single contractual authority holds.
_INTEGRATION_KEYS = frozenset({"enabled", "command", "pass_env"})


def _require_argv(value: Any, path: str) -> tuple[str, ...]:
    """Validate a canonical, structured argv (E9-S3 R1/R3).

    ``command`` must be a non-empty array of non-empty strings. A shell string
    is never accepted as the canonical form (E9-S3 R2/AC-02); each element is
    exactly one argument (INV-02).
    """

    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise _fail(
            path,
            "must be an array of strings (e.g. [\"kiro-cli\", \"--v3\"]); a shell "
            f"string is not accepted, got {type(value).__name__}",
        )
    if len(value) == 0:
        raise _fail(path, "must contain at least one element")
    argv: list[str] = []
    for index, element in enumerate(value):
        element_path = f"{path}[{index}]"
        if isinstance(element, bool) or not isinstance(element, str):
            raise _fail(
                element_path,
                f"must be a non-empty string, got {type(element).__name__}",
            )
        if element == "":
            raise _fail(element_path, "must be a non-empty string, got an empty value")
        argv.append(element)
    return tuple(argv)


def _require_pass_env(value: Any, path: str) -> tuple[str, ...]:
    """Validate the ``pass_env`` allowlist of variable names (E9-S3 R5/R6).

    Must be an array of non-empty variable *names*; inline ``KEY=value`` entries
    are rejected because names, not values, form the contract (E9-S3 R6/INV-06).

    Validation is intentionally minimal (E9-S3 R6): it does not impose a
    shell-/project-specific naming convention, so a name valid for
    ``os.environ`` (e.g. ``MY-VAR``) is accepted. The only rejections are the
    ones the contract demands (non-string, empty, inline ``=``) plus the
    NUL character, which cannot appear in an environment variable name at all.
    """

    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise _fail(
            path,
            f"must be an array of variable names, got {type(value).__name__}",
        )
    names: list[str] = []
    for index, element in enumerate(value):
        element_path = f"{path}[{index}]"
        if isinstance(element, bool) or not isinstance(element, str):
            raise _fail(
                element_path,
                f"must be a variable name string, got {type(element).__name__}",
            )
        if element == "":
            raise _fail(element_path, "must be a non-empty variable name")
        if "=" in element:
            raise _fail(
                element_path,
                "must be a variable name, not an inline KEY=value assignment",
            )
        if "\x00" in element:
            raise _fail(
                element_path,
                "must not contain a NUL character",
            )
        names.append(element)
    return tuple(names)


def _build_integrations(table: Mapping[str, Any]) -> Mapping[str, IntegrationConfig]:
    integrations: dict[str, IntegrationConfig] = {}
    for name, raw in table.items():
        path = f"integrations.{name}"
        entry = _require_table(raw, path)
        # Fail-closed: reject unsupported keys (including the retired
        # ``inherit_env``) so integrations have a single contract (E9-S3
        # R8/INV-01/INV-05, AC-06).
        _reject_unknown_keys(entry, _INTEGRATION_KEYS, path)
        enabled = _require_bool(entry.get("enabled", False), f"{path}.enabled")
        command = (
            _require_argv(entry["command"], f"{path}.command")
            if "command" in entry
            else None
        )
        pass_env = (
            _require_pass_env(entry["pass_env"], f"{path}.pass_env")
            if "pass_env" in entry
            else ()
        )
        integrations[name] = IntegrationConfig(
            name=name,
            enabled=enabled,
            command=command,
            pass_env=pass_env,
        )
    return MappingProxyType(integrations)


def build_resolved_config(
    merged: Mapping[str, Any], *, repository_root: Path
) -> ResolvedProjectConfig:
    """Validate ``merged`` and build the immutable :class:`ResolvedProjectConfig`.

    Raises :class:`ProjectConfigInvalidError` with a diagnostic pointing at the
    offending key when the structure violates the E1 contract.
    """

    root = _require_table(merged, "<config>")
    _reject_unknown_keys(root, _KNOWN_TOP_LEVEL, "<config>")

    meta = _build_meta(_require_table(root.get("meta", {}), "meta"))
    project = _build_project(_require_table(root.get("project", {}), "project"))
    target = _build_target(_require_table(root.get("target", {}), "target"))
    worktree = _build_worktree(_require_table(root.get("worktree", {}), "worktree"))
    branch = _build_branch(_require_table(root.get("branch", {}), "branch"))
    ports = _build_ports(_require_table(root.get("ports", {}), "ports"))
    capabilities = _build_capabilities(
        _require_table(root.get("capabilities", {}), "capabilities")
    )
    integrations = _build_integrations(
        _require_table(root.get("integrations", {}), "integrations")
    )

    return ResolvedProjectConfig(
        repository_root=repository_root,
        project=project,
        target=target,
        worktree=worktree,
        branch=branch,
        meta=meta,
        ports=ports,
        capabilities=capabilities,
        integrations=integrations,
    )
