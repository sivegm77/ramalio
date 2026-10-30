"""Concrete initial integrations: Kiro, VS Code, Codex, Claude (E5-S2).

Each adapter only knows its own tool (INV) and reuses the E5-S1 command-based
``BaseIntegration``: config -> argv -> launch with the worktree as cwd.  Defaults
are widely-valid conventions and always overridable per project (R5); no
personal paths are ever hardcoded.
"""

from __future__ import annotations

from .base import BaseIntegration


class KiroIntegration(BaseIntegration):
    """Open the Kiro CLI in the worktree (R1)."""

    integration_name = "kiro"
    default_command = ("kiro-cli",)


class VsCodeIntegration(BaseIntegration):
    """Open VS Code in the worktree (R2).

    The default opens the current directory; because the launcher uses the
    worktree as cwd, ``.`` resolves to the worktree, not the main checkout.
    """

    integration_name = "vscode"
    default_command = ("code", ".")


class CodexIntegration(BaseIntegration):
    """Open Codex in the worktree (R3)."""

    integration_name = "codex"
    default_command = ("codex",)


class ClaudeIntegration(BaseIntegration):
    """Open Claude in the worktree (R4)."""

    integration_name = "claude"
    default_command = ("claude",)


def initial_integrations() -> tuple[BaseIntegration, ...]:
    """Return the initial family of integration adapters (E5-S2)."""

    return (
        KiroIntegration(),
        VsCodeIntegration(),
        CodexIntegration(),
        ClaudeIntegration(),
    )
