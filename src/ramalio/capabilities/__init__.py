"""Optional capability system for ramalio (E4).

The core knows only the capability *contract* (see :mod:`.base`) and the
*registry* (see :mod:`.registry`); it never depends on any concrete capability
implementation (INV-01/INV-02).  Concrete capabilities (processes, tmux,
runtime, tunnels, ...) are added by later specs.

The default registry is empty in E4-S0: no capability is enabled by default
(INV-09), and lifecycle/status/doctor behave exactly as before when nothing is
registered.
"""

from __future__ import annotations

from .base import (
    BaseCapability,
    Capability,
    CapabilityContext,
    CapabilityDoctorCheck,
    CapabilityState,
    CapabilityStatus,
    DoctorCheckStatus,
)
from .registry import CapabilityRegistry


def default_registry() -> CapabilityRegistry:
    """Return the product's default capability registry.

    Registers the capabilities the installation ships with (E4-S2 adds the
    generic ``processes`` capability).  Registration does not enable anything:
    a capability only participates when the project's configuration sets
    ``[capabilities.<name>].enabled = true`` (INV-09, R6).  With nothing enabled,
    status/doctor behave as in E3.
    """

    from .ports_capability import PortsCapability
    from .processes import ProcessesCapability
    from .runtime import RuntimeCapability
    from .tmux import TmuxCapability
    from .tunnels import TunnelCapability
    from .bootstrap import BootstrapCapability
    from .data import DataCapability

    registry = CapabilityRegistry()
    registry.register(ProcessesCapability())
    registry.register(TmuxCapability())
    # E6-S1/E6-S2: ports registered before runtime so, on start, the reserved
    # port already exists when the runtime driver builds its environment
    # (e.g. injecting it as `port_env`). Teardown events run in reverse
    # registration order (HookRunner), so destroy/stop still release the
    # runtime/tunnel before the port pool.
    registry.register(PortsCapability())
    registry.register(RuntimeCapability())
    # E10-S3: data registered after runtime (it depends on the runtime command
    # executor) and before bootstrap. Target relative order:
    # `ports -> runtime -> data -> bootstrap -> tunnel`.
    registry.register(DataCapability())
    # E10-S2: bootstrap runs after data (dependencies may need the restored
    # database) and before tunnel.
    registry.register(BootstrapCapability())
    # Registered after runtime so, on start, runtime comes up before the tunnel
    # is opened (E6-S3 R13 start ordering).
    registry.register(TunnelCapability())
    return registry


def verify_capability_configuration(
    registry: "CapabilityRegistry",
    config,
    identity=None,
) -> None:
    """Fail closed on unknown/invalid capability configuration (E4-S0 R13).

    Shared helper so every mutable lifecycle operation (init, adopt, start,
    stop, destroy) applies the exact same fail-closed validation before running
    hooks or mutating anything: an enabled-but-unregistered capability raises
    :class:`CapabilityUnknownError`, and an enabled capability with an invalid
    namespaced config raises :class:`CapabilityConfigInvalidError`.
    """

    registry.verify_configuration(
        CapabilityContext(config=config, identity=identity)
    )


__all__ = [
    "BaseCapability",
    "Capability",
    "CapabilityContext",
    "CapabilityDoctorCheck",
    "CapabilityRegistry",
    "CapabilityState",
    "CapabilityStatus",
    "DoctorCheckStatus",
    "default_registry",
    "verify_capability_configuration",
]
