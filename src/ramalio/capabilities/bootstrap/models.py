"""Bootstrap capability configuration models and validation (E10-S2 §3).

A project declares dependency provisioning + readiness under
``[capabilities.bootstrap]``.  The core knows nothing about Composer, Laravel or
any framework (INV-07); it only turns the namespaced, validated configuration
into typed values.  Only the ``composer`` provider exists in E10-S2 and its
executable is fixed — the TOML controls ``arguments`` but never the executable
itself (R2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Mapping

from ...core.errors import CapabilityConfigInvalidError

# The single provider supported in E10-S2 (R1/R2).
PROVIDER_COMPOSER = "composer"
_SUPPORTED_PROVIDERS = frozenset({PROVIDER_COMPOSER})

# Executors (R3/R4).
EXECUTOR_HOST = "host"
EXECUTOR_RUNTIME = "runtime"
_SUPPORTED_EXECUTORS = frozenset({EXECUTOR_HOST, EXECUTOR_RUNTIME})

# The only special runtime user alias supported in E10 (R4).
RUNTIME_USER_HOST = "host"

# Default Composer arguments (spec §3): safe, non-interactive install.
_DEFAULT_COMPOSER_ARGS: tuple[str, ...] = (
    "install",
    "--no-interaction",
    "--prefer-dist",
    "--no-progress",
)

# Known top-level keys for fail-closed validation of the section.
_KNOWN_KEYS = frozenset(
    {
        "enabled",
        "provider",
        "on_init",
        "on_adopt",
        "executor",
        "arguments",
        "pass_env",
        "writable_paths",
        "runtime_service",
        "runtime_workdir",
        "runtime_user",
        "environment",
        "artifacts",
    }
)


class ArtifactKind(Enum):
    """The exact artifact kinds validated after bootstrap (R7)."""

    FILE = "file"
    DIRECTORY = "directory"
    EXECUTABLE = "executable"


@dataclass(frozen=True, slots=True)
class BootstrapArtifact:
    """A required artifact validated on the worktree filesystem (R7)."""

    path: str
    kind: ArtifactKind


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    """Validated ``[capabilities.bootstrap]`` configuration (E10-S2 §3)."""

    enabled: bool
    provider: str
    on_init: bool
    on_adopt: bool
    executor: str
    arguments: tuple[str, ...]
    pass_env: tuple[str, ...]
    writable_paths: tuple[str, ...]
    environment: Mapping[str, str]
    artifacts: tuple[BootstrapArtifact, ...]
    runtime_service: str | None = None
    runtime_workdir: str | None = None
    runtime_user: str | None = None


def _fail(message: str) -> CapabilityConfigInvalidError:
    return CapabilityConfigInvalidError(f"bootstrap: {message}")


def _require_bool(entry: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in entry:
        return default
    value = entry[key]
    if not isinstance(value, bool):
        raise _fail(f"'{key}' must be a boolean")
    return value


def _require_argv(value: Any, ctx: str) -> tuple[str, ...]:
    """Validate an argv array of non-empty strings (never a shell string)."""

    if not isinstance(value, list) or not value:
        raise _fail(f"{ctx} must be a non-empty array of strings")
    for element in value:
        if not isinstance(element, str) or element == "":
            raise _fail(f"{ctx} must contain only non-empty strings")
    return tuple(value)


def _require_names(value: Any, ctx: str) -> tuple[str, ...]:
    """Validate an allowlist of variable *names* per E9-S3 rules (R3/§3)."""

    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise _fail(f"{ctx} must be an array of variable names")
    names: list[str] = []
    for element in value:
        if isinstance(element, bool) or not isinstance(element, str):
            raise _fail(f"{ctx} must contain only variable name strings")
        if element == "":
            raise _fail(f"{ctx} must not contain an empty name")
        if "=" in element:
            raise _fail(f"{ctx} must be names, not inline KEY=value assignments")
        if "\x00" in element:
            raise _fail(f"{ctx} must not contain a NUL character")
        names.append(element)
    return tuple(names)


def _relative_worktree_path(value: str, ctx: str) -> str:
    """Validate a host path relative to and within the worktree (§3).

    Rejects absolute paths, ``..`` traversal and NUL, so a writable/artifact
    path can never escape the worktree boundary.
    """

    if not isinstance(value, str) or value == "":
        raise _fail(f"{ctx} must be a non-empty relative path")
    if "\x00" in value:
        raise _fail(f"{ctx} must not contain a NUL character")
    posix = PurePosixPath(value)
    if posix.is_absolute() or value.startswith("/"):
        raise _fail(f"{ctx} '{value}' must be relative, not absolute")
    if ".." in posix.parts:
        raise _fail(f"{ctx} '{value}' must not contain '..' segments")
    return value


def _require_paths(value: Any, ctx: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _fail(f"{ctx} must be an array of relative paths")
    return tuple(_relative_worktree_path(v, f"{ctx}[]") for v in value)


def _environment(value: Any) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise _fail("'environment' must be a table of string values")
    env: dict[str, str] = {}
    for key, val in value.items():
        if not isinstance(val, str):
            raise _fail(f"'environment[{key}]' must be a string")
        env[str(key)] = val
    return env


def _artifacts(value: Any) -> tuple[BootstrapArtifact, ...]:
    if not isinstance(value, list):
        raise _fail("'artifacts' must be an array of tables")
    artifacts: list[BootstrapArtifact] = []
    valid_kinds = {k.value for k in ArtifactKind}
    for index, raw in enumerate(value):
        ctx = f"artifacts[{index}]"
        if not isinstance(raw, dict):
            raise _fail(f"{ctx} must be a table")
        path = raw.get("path")
        path = _relative_worktree_path(path, f"{ctx}.path")
        kind = raw.get("kind")
        if kind not in valid_kinds:
            raise _fail(
                f"{ctx}.kind must be one of {sorted(valid_kinds)}, got {kind!r}"
            )
        artifacts.append(BootstrapArtifact(path=path, kind=ArtifactKind(kind)))
    return tuple(artifacts)


def parse_bootstrap_config(options: Mapping[str, Any]) -> BootstrapConfig:
    """Parse and validate the ``[capabilities.bootstrap]`` section (E10-S2 §3).

    ``options`` is the capability's namespaced configuration.  Absence of the
    section (empty options) yields a disabled config.  Unknown keys, invalid
    types and unsafe paths fail closed with
    :class:`CapabilityConfigInvalidError`.
    """

    # Fail-closed on unknown keys (spec §3 "unknown/invalid fields").
    for key in options:
        if key == "driver":
            # Never valid for bootstrap; keep the message specific.
            raise _fail("'driver' is not a valid bootstrap option")
        if key not in _KNOWN_KEYS:
            raise _fail(f"unknown option '{key}'")

    enabled = _require_bool(options, "enabled", False)

    # Absence of the section = disabled with safe defaults; a fully-absent
    # section never reaches here with content, but keep defaults coherent.
    if not enabled:
        # Still validate provider/executor if present so a disabled-but-broken
        # section is not silently accepted only because enabled=false.  Keep it
        # lenient: only enforce structure when the field is present.
        pass

    provider = options.get("provider")
    if enabled and provider is None:
        raise _fail("'provider' is required when the capability is enabled")
    if provider is not None:
        if not isinstance(provider, str) or provider not in _SUPPORTED_PROVIDERS:
            raise _fail(
                f"'provider' must be one of {sorted(_SUPPORTED_PROVIDERS)}, "
                f"got {provider!r}"
            )
    else:
        provider = PROVIDER_COMPOSER

    executor = options.get("executor", EXECUTOR_HOST)
    if not isinstance(executor, str) or executor not in _SUPPORTED_EXECUTORS:
        raise _fail(
            f"'executor' must be one of {sorted(_SUPPORTED_EXECUTORS)}, "
            f"got {executor!r}"
        )

    on_init = _require_bool(options, "on_init", True)
    on_adopt = _require_bool(options, "on_adopt", True)

    if "arguments" in options:
        arguments = _require_argv(options["arguments"], "'arguments'")
    else:
        arguments = _DEFAULT_COMPOSER_ARGS

    pass_env = (
        _require_names(options["pass_env"], "'pass_env'")
        if "pass_env" in options
        else ()
    )
    writable_paths = (
        _require_paths(options["writable_paths"], "'writable_paths'")
        if "writable_paths" in options
        else ()
    )
    environment = (
        _environment(options["environment"]) if "environment" in options else {}
    )
    artifacts = _artifacts(options["artifacts"]) if "artifacts" in options else ()

    # runtime_* handling: required per field when executor=runtime; rejected
    # fail-closed when executor=host (spec §3 defaults).
    runtime_keys = ("runtime_service", "runtime_workdir", "runtime_user")
    if executor == EXECUTOR_HOST:
        for key in runtime_keys:
            if key in options:
                raise _fail(
                    f"'{key}' is only valid when executor = 'runtime'"
                )
        runtime_service = runtime_workdir = runtime_user = None
    else:  # EXECUTOR_RUNTIME
        runtime_service = _require_runtime_str(options, "runtime_service")
        runtime_workdir = _require_runtime_str(options, "runtime_workdir")
        runtime_user = options.get("runtime_user")
        if runtime_user is None:
            raise _fail("'runtime_user' is required when executor = 'runtime'")
        if runtime_user != RUNTIME_USER_HOST:
            raise _fail(
                f"'runtime_user' only supports '{RUNTIME_USER_HOST}' in E10, "
                f"got {runtime_user!r}"
            )

    return BootstrapConfig(
        enabled=enabled,
        provider=provider,
        on_init=on_init,
        on_adopt=on_adopt,
        executor=executor,
        arguments=arguments,
        pass_env=pass_env,
        writable_paths=writable_paths,
        environment=environment,
        artifacts=artifacts,
        runtime_service=runtime_service,
        runtime_workdir=runtime_workdir,
        runtime_user=runtime_user,
    )


def _require_runtime_str(options: Mapping[str, Any], key: str) -> str:
    if key not in options:
        raise _fail(f"'{key}' is required when executor = 'runtime'")
    value = options[key]
    if not isinstance(value, str) or value == "":
        raise _fail(f"'{key}' must be a non-empty string")
    return value
