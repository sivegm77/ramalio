"""Data capability configuration and validation (E10-S3 §3).

A project declares isolated data provisioning under ``[capabilities.data]``.
Only the ``postgres`` provider exists in E10-S3.  The core knows nothing about
PostgreSQL beyond this typed configuration; no username/password/database is
configured in the TOML (the provider resolves ``POSTGRES_USER``/``POSTGRES_DB``
inside each service scope and never reads ``POSTGRES_PASSWORD``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ...core.errors import CapabilityConfigInvalidError

PROVIDER_POSTGRES = "postgres"
_SUPPORTED_PROVIDERS = frozenset({PROVIDER_POSTGRES})

CLEANUP_PRESERVE = "preserve"
CLEANUP_RUNTIME = "runtime"
_SUPPORTED_CLEANUP = frozenset({CLEANUP_PRESERVE, CLEANUP_RUNTIME})

_DEFAULT_RUNTIME_SERVICE = "db"
_DEFAULT_READINESS_TIMEOUT = 30

_KNOWN_KEYS = frozenset(
    {
        "enabled",
        "provider",
        "on_init",
        "on_adopt",
        "runtime_service",
        "readiness_timeout",
        "cleanup_mode",
    }
)


@dataclass(frozen=True, slots=True)
class DataConfig:
    """Validated ``[capabilities.data]`` configuration (E10-S3 §3)."""

    enabled: bool
    provider: str
    on_init: bool
    on_adopt: bool
    runtime_service: str
    readiness_timeout: int
    cleanup_mode: str


def _fail(message: str) -> CapabilityConfigInvalidError:
    return CapabilityConfigInvalidError(f"data: {message}")


def _require_bool(options: Mapping[str, Any], key: str, default: bool) -> bool:
    if key not in options:
        return default
    value = options[key]
    if not isinstance(value, bool):
        raise _fail(f"'{key}' must be a boolean")
    return value


def parse_data_config(options: Mapping[str, Any]) -> DataConfig:
    """Parse and validate ``[capabilities.data]`` (E10-S3 §3).

    Absence of the section (empty options) yields a disabled config.  Unknown
    keys and invalid fields fail closed with
    :class:`CapabilityConfigInvalidError`.  The cross-capability requirement of
    ``cleanup_mode='runtime'`` (a Docker Compose runtime with
    ``remove_volumes_on_destroy=true``) is enforced by the capability, which has
    access to the runtime configuration.
    """

    for key in options:
        if key not in _KNOWN_KEYS:
            raise _fail(f"unknown option '{key}'")

    enabled = _require_bool(options, "enabled", False)

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
        provider = PROVIDER_POSTGRES

    on_init = _require_bool(options, "on_init", True)
    on_adopt = _require_bool(options, "on_adopt", True)

    runtime_service = options.get("runtime_service", _DEFAULT_RUNTIME_SERVICE)
    if not isinstance(runtime_service, str) or runtime_service == "":
        raise _fail("'runtime_service' must be a non-empty string")

    readiness_timeout = options.get("readiness_timeout", _DEFAULT_READINESS_TIMEOUT)
    if isinstance(readiness_timeout, bool) or not isinstance(readiness_timeout, int):
        raise _fail("'readiness_timeout' must be an integer")
    if readiness_timeout <= 0:
        raise _fail("'readiness_timeout' must be a positive integer")

    cleanup_mode = options.get("cleanup_mode", CLEANUP_PRESERVE)
    if not isinstance(cleanup_mode, str) or cleanup_mode not in _SUPPORTED_CLEANUP:
        raise _fail(
            f"'cleanup_mode' must be one of {sorted(_SUPPORTED_CLEANUP)}, "
            f"got {cleanup_mode!r}"
        )

    return DataConfig(
        enabled=enabled,
        provider=provider,
        on_init=on_init,
        on_adopt=on_adopt,
        runtime_service=runtime_service,
        readiness_timeout=readiness_timeout,
        cleanup_mode=cleanup_mode,
    )
