"""Optional external-tool integrations for ramalio (E5).

The core never depends on a concrete tool; integrations are opt-in and resolved
by name through the registry.  The default registry is empty in E5-S1 (concrete
tools arrive in E5-S2); callers can build a custom registry for tests.
"""

from __future__ import annotations

from .base import (
    BaseIntegration,
    Integration,
    IntegrationContext,
    OpenResult,
)
from .registry import IntegrationRegistry
from .service import OpenIntegrationService


def default_integration_registry() -> IntegrationRegistry:
    """Return the product's default integration registry (E5-S2).

    Registers the initial adapter family (Kiro, VS Code, Codex, Claude).
    Registration does not enable anything: an integration participates only when
    the project sets ``[integrations.<name>].enabled = true`` and is opened
    explicitly via ``--open`` (INV: all optional).
    """

    from .adapters import initial_integrations

    return IntegrationRegistry.with_integrations(initial_integrations())


__all__ = [
    "BaseIntegration",
    "Integration",
    "IntegrationContext",
    "IntegrationRegistry",
    "OpenIntegrationService",
    "OpenResult",
    "default_integration_registry",
]
