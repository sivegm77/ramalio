"""OpenIntegrationService: open a tool after the workspace is ready (E5-S1).

Orchestrates the ``--open <tool>`` flow.  It is always invoked *after* the
workspace is created/verified (R8) and its failures never roll back the Git
workspace (R9): they surface as structured errors the caller reports as a
partial result.
"""

from __future__ import annotations

from pathlib import Path

from ..config.models import ResolvedProjectConfig
from ..core.errors import (
    IntegrationDisabledError,
    IntegrationUnavailableError,
)
from .base import IntegrationContext, OpenResult
from .registry import IntegrationRegistry


class OpenIntegrationService:
    """Resolve and open an integration for a ready workspace (7 design)."""

    def __init__(
        self,
        config: ResolvedProjectConfig,
        *,
        registry: IntegrationRegistry | None = None,
    ) -> None:
        self._config = config
        if registry is None:
            from . import default_integration_registry

            registry = default_integration_registry()
        self._registry = registry

    def open(self, *, name: str, target: str, worktree_path: Path) -> OpenResult:
        """Open integration ``name`` in the target's worktree (R4-R10).

        Distinguishes not-found (R5), disabled (R6) and unavailable (R7) before
        attempting to launch.  Never touches the Git workspace.
        """

        integration = self._registry.require(name)  # R5
        context = IntegrationContext(
            config=self._config,
            target=target,
            worktree_path=worktree_path,
        )

        if not integration.is_enabled(context):
            raise IntegrationDisabledError(
                f"integration '{name}' is not enabled in the project configuration"
            )

        integration.validate_config(context)

        if not integration.is_available(context):
            raise IntegrationUnavailableError(
                f"integration '{name}' is enabled but its command is not "
                "available on this machine"
            )

        return integration.open(context)  # R8/R10
