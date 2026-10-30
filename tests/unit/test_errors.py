from __future__ import annotations

import pytest

from ramalio.core.errors import (
    ConfigurationError,
    RamalioError,
    OperationError,
    SafetyError,
    StateError,
    UsageError,
)
from ramalio.core.result import ExitCode


@pytest.mark.parametrize(
    ("error_type", "exit_code"),
    [
        (UsageError, ExitCode.USAGE_ERROR),
        (ConfigurationError, ExitCode.CONFIGURATION_ERROR),
        (StateError, ExitCode.STATE_ERROR),
        (SafetyError, ExitCode.SAFETY_BLOCKED),
        (OperationError, ExitCode.OPERATION_FAILED),
    ],
)
def test_expected_error_categories_have_stable_exit_codes(error_type, exit_code) -> None:
    error = error_type("problem")
    assert isinstance(error, RamalioError)
    assert error.exit_code == exit_code
    assert str(error) == "problem"


def test_error_message_is_trimmed_and_stable() -> None:
    assert str(StateError("  invalid state  ")) == "invalid state"
