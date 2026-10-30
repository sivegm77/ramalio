"""Integration registry: explicit, order-preserving lookup by name (E5-S1 R2)."""

from __future__ import annotations

from collections.abc import Iterable

from ..core.errors import IntegrationNotFoundError
from .base import Integration


class IntegrationRegistry:
    """Ordered registry of known integrations (R2/R14)."""

    def __init__(self) -> None:
        self._by_name: dict[str, Integration] = {}
        self._order: list[str] = []

    def register(self, integration: Integration) -> None:
        name = integration.name
        if name in self._by_name:
            raise ValueError(f"integration '{name}' already registered")
        self._by_name[name] = integration
        self._order.append(name)

    @classmethod
    def with_integrations(
        cls, integrations: Iterable[Integration]
    ) -> "IntegrationRegistry":
        registry = cls()
        for integration in integrations:
            registry.register(integration)
        return registry

    def get(self, name: str) -> Integration | None:
        return self._by_name.get(name)

    def require(self, name: str) -> Integration:
        integration = self._by_name.get(name)
        if integration is None:
            raise IntegrationNotFoundError(
                f"integration '{name}' is not registered in this installation"
            )
        return integration

    def all(self) -> tuple[Integration, ...]:
        return tuple(self._by_name[name] for name in self._order)
