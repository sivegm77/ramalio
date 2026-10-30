"""Safe tmux adapter and configuration model (E5-S0).

All tmux invocations go through :class:`TmuxRunner` as argv lists (never a shell
string), keeping execution injection-free.  The core never imports this module;
only the tmux capability does (INV: core works without tmux).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from ...core.errors import (
    CapabilityConfigInvalidError,
    TmuxOperationFailedError,
)
from ...security import redact_diagnostic

# Ownership marker set as a tmux session environment variable (R10).
OWNER_ENV_KEY = "RAMALIO_TARGET"


class SessionPolicy(Enum):
    """Policy applied to a session on stop/destroy (R8/R9)."""

    KEEP = "keep"
    KILL = "kill"


@dataclass(frozen=True, slots=True)
class TmuxConfig:
    """Validated ``[capabilities.tmux]`` configuration (R1)."""

    session_pattern: str
    create_on_init: bool
    attach_on_init: bool
    stop_policy: SessionPolicy
    destroy_policy: SessionPolicy


_DEFAULT_PATTERN = "ramalio-{target}"


def _policy(value: Any, key: str) -> SessionPolicy:
    if value is None:
        return SessionPolicy.KEEP
    if not isinstance(value, str):
        raise CapabilityConfigInvalidError(f"tmux: {key} must be a string")
    try:
        return SessionPolicy(value)
    except ValueError as exc:
        raise CapabilityConfigInvalidError(
            f"tmux: {key} must be one of 'keep' or 'kill'"
        ) from exc


def parse_tmux_config(options: Mapping[str, Any]) -> TmuxConfig:
    """Parse and validate the tmux capability configuration (R1/R3)."""

    pattern = options.get("session_pattern", _DEFAULT_PATTERN)
    if not isinstance(pattern, str) or pattern == "":
        raise CapabilityConfigInvalidError(
            "tmux: session_pattern must be a non-empty string"
        )
    if "{target}" not in pattern:
        raise CapabilityConfigInvalidError(
            "tmux: session_pattern must contain the {target} placeholder"
        )

    for flag in ("create_on_init", "attach_on_init"):
        if flag in options and not isinstance(options[flag], bool):
            raise CapabilityConfigInvalidError(f"tmux: {flag} must be a boolean")

    return TmuxConfig(
        session_pattern=pattern,
        create_on_init=bool(options.get("create_on_init", False)),
        attach_on_init=bool(options.get("attach_on_init", False)),
        stop_policy=_policy(options.get("stop_policy", "keep"), "stop_policy"),
        destroy_policy=_policy(options.get("destroy_policy", "keep"), "destroy_policy"),
    )


# tmux session names cannot contain '.' or ':' and must be non-empty (R3).
_FORBIDDEN_SESSION_CHARS = frozenset({".", ":", "\n", "\t"})


def derive_session_name(pattern: str, target: str) -> str:
    """Derive a deterministic, valid tmux session name (R3)."""

    name = pattern.replace("{target}", target)
    if name == "" or any(ch in _FORBIDDEN_SESSION_CHARS for ch in name):
        raise CapabilityConfigInvalidError(
            f"tmux: derived session name '{name}' is invalid"
        )
    return name


class TmuxRunner:
    """Argv-only adapter over the tmux CLI (7 design)."""

    def __init__(self, executable: str | None = None) -> None:
        self._exe = executable or "tmux"
        from ...security import SafeProcessRunner

        self._runner = SafeProcessRunner()

    @property
    def available(self) -> bool:
        return shutil.which(self._exe) is not None

    def _run(self, *args: str, check: bool = False) -> subprocess.CompletedProcess:
        # E7-S2 R6/R7: execute through the central SafeProcessRunner (argv-only,
        # shell=False, controlled environment) instead of a bespoke subprocess
        # call.  tmux's own working directory is irrelevant (session cwd is set
        # via ``-c``), so the current directory is used as the spec cwd.
        from pathlib import Path

        from ...security import CommandSpec

        try:
            return self._runner.run(
                CommandSpec(argv=(self._exe, *args), cwd=Path.cwd())
            )
        except OSError as exc:  # pragma: no cover - tmux missing / not runnable
            raise TmuxOperationFailedError(f"failed to invoke tmux: {exc}") from exc

    def has_session(self, name: str) -> bool:
        result = self._run("has-session", "-t", f"={name}")
        return result.returncode == 0

    def new_session(self, name: str, *, cwd: str | None = None) -> None:
        args = ["new-session", "-d", "-s", name]
        if cwd is not None:
            args += ["-c", cwd]
        result = self._run(*args)
        if result.returncode != 0:
            raise TmuxOperationFailedError(
                f"tmux new-session failed: {redact_diagnostic(result.stderr)}"
            )

    def kill_session(self, name: str) -> None:
        result = self._run("kill-session", "-t", f"={name}")
        if result.returncode != 0 and "can't find session" not in result.stderr:
            raise TmuxOperationFailedError(
                f"tmux kill-session failed: {redact_diagnostic(result.stderr)}"
            )

    def set_session_env(self, name: str, key: str, value: str) -> None:
        result = self._run("set-environment", "-t", f"={name}", key, value)
        if result.returncode != 0:  # pragma: no cover - environment dependent
            raise TmuxOperationFailedError(
                f"tmux set-environment failed: {redact_diagnostic(result.stderr)}"
            )

    def get_session_env(self, name: str, key: str) -> str | None:
        result = self._run("show-environment", "-t", f"={name}", key)
        if result.returncode != 0:
            return None
        # Output form: KEY=value  (or "-KEY" when unset)
        line = result.stdout.strip()
        prefix = f"{key}="
        if line.startswith(prefix):
            return line[len(prefix) :]
        return None
