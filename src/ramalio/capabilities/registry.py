"""Capability registry: explicit, order-preserving registration (E4-S0).

The registry is the single place capabilities are made known to the product.
Registration is explicit and in-code (7.3): the registry never imports modules
named by configuration (INV-07/R4).  Iteration order follows registration order
so behavior is deterministic and not tied to dict hashing (R14).

Responsibilities (R3):

* register known implementations, rejecting duplicate names (R2);
* look a capability up by name;
* enumerate all capabilities and the subset enabled by configuration;
* surface configuration that enables an unknown capability (R13);
* provide error-bounded status/doctor collection so a single misbehaving
  capability never collapses the whole result (R10/7.4).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..core.errors import (
    CapabilityConfigInvalidError,
    CapabilityDuplicateError,
    CapabilityUnknownError,
    RamalioError,
)
from .base import (
    Capability,
    CapabilityContext,
    CapabilityDoctorCheck,
    CapabilityState,
    CapabilityStatus,
    DoctorCheckStatus,
)


class CapabilityRegistry:
    """Ordered registry of known capabilities (R3/R14)."""

    def __init__(self) -> None:
        # Insertion order is preserved by dict in Python 3.7+, but we keep an
        # explicit order list to make the contract obvious and independent of
        # that implementation detail (R14).
        self._by_name: dict[str, Capability] = {}
        self._order: list[str] = []

    # --- registration -----------------------------------------------------

    def register(self, capability: Capability) -> None:
        """Register ``capability``; reject a duplicate name (R2)."""

        name = capability.name
        if name in self._by_name:
            raise CapabilityDuplicateError(
                f"a capability named '{name}' is already registered"
            )
        self._by_name[name] = capability
        self._order.append(name)

    @classmethod
    def with_capabilities(
        cls, capabilities: Iterable[Capability]
    ) -> "CapabilityRegistry":
        """Build a registry from an ordered iterable of capabilities."""

        registry = cls()
        for capability in capabilities:
            registry.register(capability)
        return registry

    # --- lookup / enumeration --------------------------------------------

    def get(self, name: str) -> Capability | None:
        """Return the capability registered under ``name`` or ``None``."""

        return self._by_name.get(name)

    def all(self) -> tuple[Capability, ...]:
        """Return all registered capabilities in registration order (R14)."""

        return tuple(self._by_name[name] for name in self._order)

    def enabled(self, context: CapabilityContext) -> tuple[Capability, ...]:
        """Return capabilities enabled by configuration, in order (R3/R6)."""

        return tuple(cap for cap in self.all() if cap.is_enabled(context))

    # --- configuration coherence -----------------------------------------

    def verify_configuration(self, context: CapabilityContext) -> None:
        """Fail on configuration that enables an unknown capability (R13).

        Any ``[capabilities.<name>]`` with ``enabled = true`` whose name is not
        registered raises :class:`CapabilityUnknownError`.  Then each enabled,
        known capability validates its own namespaced config (R12), surfacing
        :class:`CapabilityConfigInvalidError` with the capability name.
        """

        for name, entry in context.config.capabilities.items():
            if entry.enabled and name not in self._by_name:
                raise CapabilityUnknownError(
                    f"configuration enables unknown capability '{name}'; "
                    "it is not registered in this installation"
                )

        for capability in self.enabled(context):
            capability.validate_config(context)

    # --- error-bounded collection ----------------------------------------

    def collect_status(
        self, context: CapabilityContext
    ) -> tuple[CapabilityStatus, ...]:
        """Return status for each enabled capability, isolating failures (R10).

        A capability that raises while reporting status is surfaced as an
        ``ERROR`` status instead of propagating, so the caller's overall result
        (e.g. ``ramalio status``) never collapses (7.4).
        """

        results: list[CapabilityStatus] = []
        for capability in self.enabled(context):
            try:
                results.append(capability.status(context))
            except Exception as exc:  # noqa: BLE001 - deliberate error boundary
                results.append(
                    CapabilityStatus(
                        name=capability.name,
                        state=CapabilityState.ERROR,
                        summary="capability status failed",
                        details=_safe_detail(exc),
                    )
                )
        return tuple(results)

    def collect_doctor_checks(
        self, context: CapabilityContext
    ) -> tuple[CapabilityDoctorCheck, ...]:
        """Collect doctor checks from all registered capabilities (R11).

        Every registered capability may contribute checks (even disabled ones
        can report that they are disabled); a capability that raises is turned
        into a single FAIL check rather than aborting doctor (7.4).
        """

        checks: list[CapabilityDoctorCheck] = []
        for capability in self.all():
            try:
                checks.extend(capability.doctor_checks(context))
            except Exception as exc:  # noqa: BLE001 - deliberate error boundary
                checks.append(
                    CapabilityDoctorCheck(
                        check_id=f"CAPABILITY_{capability.name.upper()}",
                        status=DoctorCheckStatus.FAIL,
                        summary=f"capability '{capability.name}' check failed",
                        details=_safe_detail(exc),
                    )
                )
        return tuple(checks)


def _safe_detail(exc: Exception) -> str:
    """Render an exception as a stable detail string.

    Expected product errors keep their message; unexpected exceptions are
    summarized without leaking a traceback into user-facing output.
    """

    if isinstance(exc, RamalioError):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"
