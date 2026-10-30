from __future__ import annotations

import pytest

from ramalio.core.result import CommandResult, ExitCode


def test_default_result_is_success() -> None:
    result = CommandResult()
    assert result.code == 0
    assert result.stdout is None
    assert result.stderr is None


def test_result_carries_stdout_and_stderr() -> None:
    result = CommandResult(ExitCode.OPERATION_FAILED, stdout="value", stderr="diagnostic")
    assert result.code == 6
    assert result.stdout == "value"
    assert result.stderr == "diagnostic"


@pytest.mark.parametrize("code", [-1, 256, 999])
def test_result_rejects_invalid_process_exit_codes(code: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 255"):
        CommandResult(code)


def test_result_rejects_non_text_channels() -> None:
    with pytest.raises(TypeError, match="stdout"):
        CommandResult(stdout=123)  # type: ignore[arg-type]
