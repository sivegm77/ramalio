"""The ``none`` runtime driver: functional no-op base behavior (E6-S0 R3).

``none`` is a first-class driver, not a scattered special case.  start/stop/
cleanup are successful no-ops; status reports NOT_APPLICABLE.
"""

from __future__ import annotations

from .base import (
    RuntimeDoctorCheck,
    RuntimeDriver,
    RuntimeResult,
    RuntimeState,
    RuntimeWorkspace,
)

DRIVER_NAME = "none"


class NoneRuntimeDriver:
    """A driver that manages no runtime resources (R3)."""

    @property
    def name(self) -> str:
        return DRIVER_NAME

    def doctor(
        self, workspace: RuntimeWorkspace | None
    ) -> tuple[RuntimeDoctorCheck, ...]:
        return (
            RuntimeDoctorCheck(
                check_id="RUNTIME_NONE",
                ok=True,
                summary="no runtime configured",
            ),
        )

    def start(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        return RuntimeResult(RuntimeState.NOT_APPLICABLE, "no runtime to start")

    def provision(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        # E10-S1 R1: provisioning a non-existent runtime is a successful no-op.
        return RuntimeResult(RuntimeState.NOT_APPLICABLE, "no runtime to provision")

    def stop(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        return RuntimeResult(RuntimeState.NOT_APPLICABLE, "no runtime to stop")

    def status(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        return RuntimeResult(RuntimeState.NOT_APPLICABLE, "no runtime configured")

    def cleanup(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        return RuntimeResult(RuntimeState.NOT_APPLICABLE, "no runtime to clean up")


# Verify the driver satisfies the protocol at import time.
_driver: RuntimeDriver = NoneRuntimeDriver()
