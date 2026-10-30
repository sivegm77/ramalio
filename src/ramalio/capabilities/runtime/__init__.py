"""Optional runtime capability and driver contract (E6-S0)."""

from __future__ import annotations

from .base import (
    RuntimeCommandExecutor,
    RuntimeDoctorCheck,
    RuntimeDriver,
    RuntimeExecRequest,
    RuntimeExecResult,
    RuntimeResult,
    RuntimeScope,
    RuntimeState,
    RuntimeWorkspace,
)
from .capability import CAPABILITY_NAME, RuntimeCapability, register_driver
from .docker_compose import DRIVER_NAME as DOCKER_COMPOSE_DRIVER, make_driver
from .none_driver import NoneRuntimeDriver

# Register the optional Docker Compose driver so a project can select it via
# `[capabilities.runtime].driver = "docker-compose"`. Selecting it is opt-in;
# Docker is never required by the core.
register_driver(DOCKER_COMPOSE_DRIVER, make_driver)

__all__ = [
    "CAPABILITY_NAME",
    "DOCKER_COMPOSE_DRIVER",
    "NoneRuntimeDriver",
    "RuntimeCapability",
    "RuntimeCommandExecutor",
    "RuntimeDoctorCheck",
    "RuntimeDriver",
    "RuntimeExecRequest",
    "RuntimeExecResult",
    "RuntimeResult",
    "RuntimeScope",
    "RuntimeState",
    "RuntimeWorkspace",
    "register_driver",
]
