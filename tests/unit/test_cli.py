from __future__ import annotations

import os
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

from ramalio import __version__
from ramalio.cli import PUBLIC_COMMANDS, main
from ramalio.core.errors import (
    ConfigurationError,
    OperationError,
    SafetyError,
    StateError,
    UsageError,
)
from ramalio.core.result import CommandResult, ExitCode

TARGET_COMMANDS = ("init", "adopt", "destroy", "status", "start", "stop")
NO_TARGET_COMMANDS = ("list", "doctor")
RESERVED_NO_TARGET_COMMANDS: tuple[str, ...] = ()
# All public commands are implemented as of E3-S3 (doctor). No E0 placeholders
# remain reserved.
_IMPLEMENTED_COMMANDS = (
    "init", "adopt", "destroy", "list", "status", "start", "stop", "doctor",
)
RESERVED_COMMANDS = tuple(c for c in PUBLIC_COMMANDS if c not in _IMPLEMENTED_COMMANDS)
RESERVED_TARGET_COMMANDS = tuple(
    c for c in TARGET_COMMANDS if c not in _IMPLEMENTED_COMMANDS
)


def invoke(args, *, handlers=None):
    stdout = StringIO()
    stderr = StringIO()
    code = main(args, stdout=stdout, stderr=stderr, handlers=handlers)
    return code, stdout.getvalue(), stderr.getvalue()


def test_global_help_lists_exact_public_command_family() -> None:
    code, stdout, stderr = invoke(["--help"])
    assert code == 0
    assert stderr == ""
    for command in PUBLIC_COMMANDS:
        assert command in stdout
    assert stdout.endswith("\n")


def test_version_comes_from_package_single_source() -> None:
    code, stdout, stderr = invoke(["--version"])
    assert code == 0
    assert stdout == f"ramalio {__version__}\n"
    assert stderr == ""


def test_unknown_command_is_usage_error_on_stderr() -> None:
    code, stdout, stderr = invoke(["does-not-exist"])
    assert code == ExitCode.USAGE_ERROR
    assert stdout == ""
    assert "invalid choice" in stderr
    assert stderr.startswith("error: ")
    assert stderr.endswith("\n")


def test_missing_command_is_usage_error() -> None:
    code, stdout, stderr = invoke([])
    assert code == ExitCode.USAGE_ERROR
    assert stdout == ""
    assert "required" in stderr


@pytest.mark.parametrize("command", TARGET_COMMANDS)
def test_target_commands_require_target(command: str) -> None:
    code, stdout, stderr = invoke([command])
    assert code == ExitCode.USAGE_ERROR
    assert stdout == ""
    assert "required" in stderr


@pytest.mark.parametrize("command", RESERVED_NO_TARGET_COMMANDS)
def test_commands_without_target_parse_without_target(command: str) -> None:
    code, stdout, stderr = invoke([command])
    assert code == ExitCode.NOT_IMPLEMENTED
    assert stdout == ""
    assert command in stderr


@pytest.mark.parametrize("command", RESERVED_TARGET_COMMANDS)
def test_target_commands_reach_placeholder_with_arbitrary_target(command: str) -> None:
    # E0 reserves arity only. Semantic target validation belongs to E1.
    code, stdout, stderr = invoke([command, "anything goes in E0"])
    assert code == ExitCode.NOT_IMPLEMENTED
    assert stdout == ""
    assert command in stderr


@pytest.mark.parametrize("command", RESERVED_COMMANDS)
def test_all_reserved_commands_return_not_implemented(command: str) -> None:
    args = [command, "TASK-1"] if command in TARGET_COMMANDS else [command]
    code, stdout, stderr = invoke(args)
    assert code == ExitCode.NOT_IMPLEMENTED
    assert stdout == ""
    assert stderr == f"ramalio {command}: command reserved but not implemented in E0\n"


@pytest.mark.parametrize("command", RESERVED_COMMANDS)
def test_placeholders_have_no_filesystem_side_effects(command: str, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    before = sorted(tmp_path.iterdir())
    args = [command, "TASK-1"] if command in TARGET_COMMANDS else [command]
    code, _, _ = invoke(args)
    after = sorted(tmp_path.iterdir())
    assert code == ExitCode.NOT_IMPLEMENTED
    assert before == after == []


def test_command_help_is_successful_and_does_not_dispatch() -> None:
    code, stdout, stderr = invoke(["init", "--help"])
    assert code == 0
    assert "TARGET" in stdout
    assert stderr == ""


def test_wrapper_keeps_primary_output_and_diagnostic_separate() -> None:
    def handler(_args):
        return CommandResult(0, stdout="machine-value\n\n", stderr="warning\n\n")

    code, stdout, stderr = invoke(["list"], handlers={"list": handler})
    assert code == 0
    assert stdout == "machine-value\n"
    assert stderr == "warning\n"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (UsageError("bad usage"), 2),
        (ConfigurationError("bad config"), 3),
        (StateError("bad state"), 4),
        (SafetyError("blocked"), 5),
        (OperationError("operation failed"), 6),
    ],
)
def test_expected_errors_map_to_stable_exit_codes(error, expected_code: int) -> None:
    def handler(_args):
        raise error

    code, stdout, stderr = invoke(["list"], handlers={"list": handler})
    assert code == expected_code
    assert stdout == ""
    assert stderr == f"error: {error}\n"


def test_unexpected_exception_returns_70_without_traceback() -> None:
    def handler(_args):
        raise RuntimeError("sensitive internals")

    code, stdout, stderr = invoke(["list"], handlers={"list": handler})
    assert code == ExitCode.INTERNAL_ERROR
    assert stdout == ""
    assert stderr == "error: unexpected internal error\n"
    assert "Traceback" not in stderr
    assert "sensitive internals" not in stderr


def test_handler_must_return_command_result() -> None:
    def handler(_args):
        return "not-a-result"

    code, stdout, stderr = invoke(["list"], handlers={"list": handler})
    assert code == ExitCode.INTERNAL_ERROR
    assert stdout == ""
    assert stderr == "error: unexpected internal error\n"


def test_python_module_execution_has_stable_cli_contract(tmp_path: Path) -> None:
    # The module is runnable via `python -m` and honors the stable error
    # contract.  An unknown command is a usage error on stderr regardless of
    # which lifecycle features are implemented.
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "ramalio.cli", "does-not-exist"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == ExitCode.USAGE_ERROR
    assert completed.stdout == ""
    assert completed.stderr.endswith("\n")
