"""Process item configuration and runtime models (E4-S2).

The core knows nothing about queue workers or dev servers (INV-04); a project
declares processes under ``[capabilities.processes]`` and this module turns that
namespaced data into validated, typed items.  Commands are modeled as argv lists
(INV-02); a raw shell string is intentionally not accepted (out of scope).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from ...core.errors import (
    CapabilityConfigInvalidError,
    ProcessDuplicateNameError,
)

# Safe default stop timeout in seconds (R12).
DEFAULT_STOP_TIMEOUT = 10.0


class ProcessState(Enum):
    """Per-item process state (R13)."""

    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    STALE = "STALE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ProcessItem:
    """A single declared managed process (R1)."""

    name: str
    command: tuple[str, ...]
    cwd: str = "."
    environment: Mapping[str, str] = field(default_factory=dict)
    start_on_init: bool = False
    start_on_start: bool = True
    stop_on_stop: bool = True
    stop_on_destroy: bool = True
    stop_timeout: float = DEFAULT_STOP_TIMEOUT


@dataclass(frozen=True, slots=True)
class ProcessStatus:
    """Observed status of one process item (R13)."""

    name: str
    state: ProcessState
    pid: int | None
    summary: str


def _require_list_of_str(value: Any, ctx: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise CapabilityConfigInvalidError(
            f"processes: {ctx} must be a non-empty list of strings"
        )
    for element in value:
        if not isinstance(element, str) or element == "":
            raise CapabilityConfigInvalidError(
                f"processes: {ctx} must contain only non-empty strings"
            )
    return tuple(value)


def _optional_bool(entry: Mapping[str, Any], key: str, default: bool, ctx: str) -> bool:
    if key not in entry:
        return default
    value = entry[key]
    if not isinstance(value, bool):
        raise CapabilityConfigInvalidError(
            f"processes: {ctx}.{key} must be a boolean"
        )
    return value


def _environment(entry: Mapping[str, Any], ctx: str) -> Mapping[str, str]:
    raw = entry.get("environment", {})
    if not isinstance(raw, dict):
        raise CapabilityConfigInvalidError(
            f"processes: {ctx}.environment must be a table of strings"
        )
    env: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise CapabilityConfigInvalidError(
                f"processes: {ctx}.environment['{key}'] must be a string"
            )
        env[str(key)] = value
    return env


def parse_process_items(options: Mapping[str, Any]) -> tuple[ProcessItem, ...]:
    """Parse and validate ``[capabilities.processes]`` items (R1-R5, R12).

    ``options`` is the capability's namespaced configuration minus ``enabled``.
    Raises :class:`CapabilityConfigInvalidError` on structural defects and
    :class:`ProcessDuplicateNameError` on duplicate item names (R2).
    """

    raw_items = options.get("items", [])
    if not isinstance(raw_items, list):
        raise CapabilityConfigInvalidError(
            "processes: 'items' must be an array of tables"
        )

    items: list[ProcessItem] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items):
        ctx = f"items[{index}]"
        if not isinstance(raw, dict):
            raise CapabilityConfigInvalidError(
                f"processes: {ctx} must be a table"
            )
        name = raw.get("name")
        if not isinstance(name, str) or name == "":
            raise CapabilityConfigInvalidError(
                f"processes: {ctx}.name must be a non-empty string"
            )
        if name in seen:
            raise ProcessDuplicateNameError(
                f"processes: duplicate process name '{name}'"
            )
        seen.add(name)

        command = _require_list_of_str(raw.get("command"), f"{ctx}.command")

        cwd = raw.get("cwd", ".")
        if not isinstance(cwd, str) or cwd == "":
            raise CapabilityConfigInvalidError(
                f"processes: {ctx}.cwd must be a non-empty string"
            )
        # cwd must stay within the worktree boundary (R4): no absolute paths,
        # no parent traversal.
        if cwd.startswith("/") or ".." in cwd.split("/"):
            raise CapabilityConfigInvalidError(
                f"processes: {ctx}.cwd '{cwd}' must be relative and within the "
                "worktree"
            )

        timeout = raw.get("stop_timeout", DEFAULT_STOP_TIMEOUT)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise CapabilityConfigInvalidError(
                f"processes: {ctx}.stop_timeout must be a number"
            )
        if timeout <= 0:
            raise CapabilityConfigInvalidError(
                f"processes: {ctx}.stop_timeout must be positive"
            )

        items.append(
            ProcessItem(
                name=name,
                command=command,
                cwd=cwd,
                environment=_environment(raw, ctx),
                start_on_init=_optional_bool(raw, "start_on_init", False, ctx),
                start_on_start=_optional_bool(raw, "start_on_start", True, ctx),
                stop_on_stop=_optional_bool(raw, "stop_on_stop", True, ctx),
                stop_on_destroy=_optional_bool(raw, "stop_on_destroy", True, ctx),
                stop_timeout=float(timeout),
            )
        )

    return tuple(items)
