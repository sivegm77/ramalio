"""Integration contract: opening external tools from a workspace (E5-S1).

An *integration* takes a ready workspace and opens an external tool (editor, AI
CLI, ...) in it.  The core knows only this contract, never a concrete tool
(INV: no integration is a core dependency).  Opening a tool never changes the
fundamental semantics of init/start and never rolls back the Git workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..config.models import IntegrationConfig, ResolvedProjectConfig


@dataclass(frozen=True, slots=True)
class IntegrationContext:
    """Context handed to an integration to open a tool (R10/R11)."""

    config: ResolvedProjectConfig
    target: str
    worktree_path: Path

    def integration_config(self, name: str) -> IntegrationConfig | None:
        return self.config.integrations.get(name)


@dataclass(frozen=True, slots=True)
class OpenResult:
    """Structured result of opening an integration (R9/R13)."""

    name: str
    opened: bool
    summary: str
    details: str | None = None
    command: tuple[str, ...] = ()
    cwd: str | None = None


@runtime_checkable
class Integration(Protocol):
    """The integration contract (R1)."""

    @property
    def name(self) -> str:
        ...

    def is_enabled(self, context: IntegrationContext) -> bool:
        ...

    def is_available(self, context: IntegrationContext) -> bool:
        ...

    def validate_config(self, context: IntegrationContext) -> None:
        ...

    def open(self, context: IntegrationContext) -> OpenResult:
        ...


class BaseIntegration:
    """Convenience base for command-based integrations.

    A concrete integration typically only needs a stable name; the command is
    read from ``[integrations.<name>].command`` and executed with the worktree
    as cwd.  Availability is derived from the command's executable being on PATH.
    """

    integration_name: str = ""
    #: Optional default argv used when the project does not declare a command.
    #: Must be a widely-valid convention, never a personal path (E5-S2 R5).
    default_command: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        if not self.integration_name:
            raise ValueError("integration_name must be set")
        return self.integration_name

    def is_enabled(self, context: IntegrationContext) -> bool:
        entry = context.integration_config(self.name)
        return entry is not None and entry.enabled

    def _command(self, context: IntegrationContext) -> list[str]:
        entry = context.integration_config(self.name)
        if entry is not None and entry.command is not None:
            # ``command`` is canonical, structured argv (E9-S3 R1/R2/INV-02):
            # each element is one argument and no shell tokenization is applied.
            return list(entry.command)
        # Fall back to the adapter's default convention when configured (R5).
        return list(self.default_command)

    def is_available(self, context: IntegrationContext) -> bool:
        import shutil

        command = self._command(context)
        if not command:
            return False
        return shutil.which(command[0]) is not None or Path(command[0]).exists()

    def validate_config(self, context: IntegrationContext) -> None:
        from ..core.errors import IntegrationConfigInvalidError

        entry = context.integration_config(self.name)
        if entry is None or not entry.enabled:
            return
        if not self._command(context):
            raise IntegrationConfigInvalidError(
                f"integration '{self.name}': a non-empty command is required"
            )
        # Structural validation of command/pass_env/unsupported keys (including
        # the retired ``inherit_env``) already happened in the config loader
        # (E9-S3 R3/R6/R8, fail-closed). Nothing further to enforce here.

    def _env_policy(self, context: IntegrationContext) -> dict[str, str]:
        """Resolve the explicit env overlay for this integration (E9-S3 R4/R5).

        An integration may declare, in its ``[integrations.<name>]`` section:

        * ``pass_env = ["AWS_PROFILE", "AWS_REGION", ...]`` — an allowlist of
          host variables to forward explicitly. No secret *values* live in the
          versioned TOML, only variable *names* (INV-06).

        Returns the extra environment mapping to overlay on the controlled base.
        By default nothing beyond the controlled base is inherited (INV-03), so a
        tool that needs host variables must opt in explicitly via ``pass_env``
        (INV-04). ``inherit_env`` is not part of the public contract (INV-05).

        A name declared in ``pass_env`` that is absent from the current
        environment is simply not forwarded; the core neither invents a value
        nor reads alternative files to resolve it (E9-S3 R7).
        """

        import os

        entry = context.integration_config(self.name)
        pass_env = entry.pass_env if entry is not None else ()
        extra: dict[str, str] = {}
        for name in pass_env:
            value = os.environ.get(name)
            if value is not None:
                extra[name] = value
        return extra

    def open(self, context: IntegrationContext) -> OpenResult:
        import subprocess

        from ..core.errors import IntegrationOpenFailedError
        from ..security import CommandSpec, SafeProcessRunner

        command = self._command(context)
        extra_env = self._env_policy(context)
        try:
            # E7-S2 R6/R7 + E9-S3 R9: launch through the central
            # SafeProcessRunner (argv-only, shell=False, controlled environment)
            # rather than a bespoke subprocess call. Integrations are detached
            # background processes, so popen() is the appropriate controlled
            # primitive. The env overlay is the explicit ``pass_env`` allowlist
            # only; by default just the controlled base is passed (INV-03).
            SafeProcessRunner().popen(
                CommandSpec(
                    argv=tuple(command),
                    cwd=Path(context.worktree_path),
                    env=extra_env,
                ),
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            raise IntegrationOpenFailedError(
                f"integration '{self.name}': failed to open {command!r}: {exc}"
            ) from exc
        return OpenResult(
            name=self.name,
            opened=True,
            summary=f"opened {self.name}",
            command=tuple(command),
            cwd=str(context.worktree_path),
        )
