"""Common command result contract for ramalio."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ExitCode(IntEnum):
    """Stable process exit codes defined by E0-S1."""

    OK = 0
    USAGE_ERROR = 2
    CONFIGURATION_ERROR = 3
    STATE_ERROR = 4
    SAFETY_BLOCKED = 5
    OPERATION_FAILED = 6
    INTERNAL_ERROR = 70
    NOT_IMPLEMENTED = 78


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Transport-neutral result returned by CLI command handlers.

    Handlers do not print.  The CLI wrapper owns rendering to stdout/stderr so
    future lifecycle code can remain independent from terminal concerns.
    """

    exit_code: int | ExitCode = ExitCode.OK
    stdout: str | None = None
    stderr: str | None = None

    def __post_init__(self) -> None:
        code = int(self.exit_code)
        if not 0 <= code <= 255:
            raise ValueError("exit_code must be between 0 and 255")

        for field_name, value in (("stdout", self.stdout), ("stderr", self.stderr)):
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{field_name} must be str or None")

    @property
    def code(self) -> int:
        """Return a plain integer suitable for ``sys.exit``."""

        return int(self.exit_code)
