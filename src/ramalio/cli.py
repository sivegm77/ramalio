"""Command-line interface for ramalio.

Stage E0 freezes the public CLI surface and common output/error contracts.  It
intentionally does not implement project configuration, target semantics, Git
lifecycle operations, capabilities, integrations, runtimes or resources.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from typing import TextIO

from . import __version__
from .core.errors import RamalioError, UsageError
from .core.result import CommandResult, ExitCode

Handler = Callable[[argparse.Namespace], CommandResult]

_COMMANDS_WITH_TARGET = ("init", "adopt", "destroy", "status", "start", "stop")
_COMMANDS_WITHOUT_TARGET = ("list", "doctor")
PUBLIC_COMMANDS = (
    "init",
    "adopt",
    "destroy",
    "list",
    "status",
    "doctor",
    "start",
    "stop",
)


class _ArgumentParser(argparse.ArgumentParser):
    """ArgumentParser that reports usage defects through the common error map."""

    def error(self, message: str) -> None:
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the E0 public parser without touching project or Git state."""

    parser = _ArgumentParser(
        prog="ramalio",
        description="Administra workspaces aislados basados en Git worktrees.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    descriptions = {
        "init": "Crear un workspace administrado.",
        "adopt": "Adoptar trabajo existente como workspace administrado.",
        "destroy": "Retirar de forma segura un workspace administrado.",
        "list": "Listar workspaces administrados.",
        "status": "Mostrar el estado de un workspace.",
        "doctor": "Diagnosticar proyecto y entorno.",
        "start": "Reactivar recursos de un workspace existente.",
        "stop": "Detener recursos sin destruir el workspace.",
    }

    for command in PUBLIC_COMMANDS:
        subparser = subparsers.add_parser(command, help=descriptions[command], description=descriptions[command])
        if command in _COMMANDS_WITH_TARGET:
            subparser.add_argument("target", metavar="TARGET")
        # E5-S1: init/start can open an external tool integration after the
        # workspace is ready. --open is optional and never changes lifecycle
        # semantics.
        if command in ("init", "start"):
            subparser.add_argument(
                "--open",
                metavar="TOOL",
                dest="open_tool",
                default=None,
                help="Abrir una integración (herramienta) tras preparar el workspace.",
            )
        subparser.set_defaults(_handler_name=command)

    return parser


def _placeholder_handler(command: str) -> Handler:
    """Return an E0 placeholder with no side effects."""

    def handler(_args: argparse.Namespace) -> CommandResult:
        return CommandResult(
            exit_code=ExitCode.NOT_IMPLEMENTED,
            stderr=f"ramalio {command}: command reserved but not implemented in E0",
        )

    return handler


def _init_handler(args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio init <target>`` (E2-S1 T9).

    The handler stays thin: it delegates the whole pipeline to
    :class:`~ramalio.core.init.InitWorkspaceService` and returns a
    :class:`CommandResult`.  It never prints and never contains lifecycle logic
    (handlers-do-not-print contract).  Expected product errors propagate to
    :func:`main`, which maps them to stable exit codes and stderr.
    """

    # Imported lazily so the E0 parser/render contract has no import-time
    # dependency on the lifecycle stack.
    from .core.init import InitWorkspaceService

    service = InitWorkspaceService.from_directory()
    outcome = service.run(args.target)
    return _maybe_open(
        args, target=outcome.target, worktree_path=outcome.worktree_path,
        primary=outcome.render_lines(),
    )


def _maybe_open(args, *, target, worktree_path, primary: str) -> CommandResult:
    """Optionally open an integration after a ready workspace (E5-S1 R8/R9).

    The workspace is already created/verified when this runs.  A failure to open
    the tool never rolls back the workspace; it is reported as a partial result
    (stdout keeps the primary success output, stderr explains the open failure)
    with a non-zero exit code so the caller knows the tool did not open.
    """

    open_tool = getattr(args, "open_tool", None)
    if not open_tool:
        return CommandResult(exit_code=ExitCode.OK, stdout=primary)

    from .core.errors import RamalioError
    from .integrations import OpenIntegrationService
    from .config.loader import resolve_project_config

    try:
        config = resolve_project_config()
        result = OpenIntegrationService(config).open(
            name=open_tool, target=target, worktree_path=worktree_path
        )
    except RamalioError as exc:
        # R9: workspace stays intact; report partial result.
        return CommandResult(
            exit_code=exc.exit_code,
            stdout=primary,
            stderr=f"workspace ready but could not open '{open_tool}': {exc}",
        )

    return CommandResult(
        exit_code=ExitCode.OK,
        stdout=f"{primary}\nopened: {result.name}",
    )


def _adopt_handler(args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio adopt <target>`` (E2-S2 T9).

    Thin like the init handler: it delegates the whole pipeline to
    :class:`~ramalio.core.adopt.AdoptWorkspaceService` and returns a
    :class:`CommandResult`.  It never prints and holds no lifecycle logic;
    expected product errors propagate to :func:`main` for stable exit-code
    mapping.
    """

    from .core.adopt import AdoptWorkspaceService

    service = AdoptWorkspaceService.from_directory()
    outcome = service.run(args.target)
    return CommandResult(exit_code=ExitCode.OK, stdout=outcome.render_lines())


def _destroy_handler(args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio destroy <target>`` (E2-S3 T10).

    Thin handler delegating to
    :class:`~ramalio.core.destroy.DestroyWorkspaceService`.  Expected
    product errors propagate to :func:`main` for stable exit-code mapping; a
    controlled partial closure (worktree removed, branch preserved) is a
    successful result, not an error.
    """

    from .core.destroy import DestroyWorkspaceService

    service = DestroyWorkspaceService.from_directory()
    outcome = service.run(args.target)
    return CommandResult(exit_code=ExitCode.OK, stdout=outcome.render_lines())


def _list_handler(_args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio list`` (E3-S0 T8).

    Thin handler delegating to
    :class:`~ramalio.core.list_workspaces.ListWorkspacesService`.  It is
    strictly read-only and returns a compact structured listing.
    """

    from .core.list_workspaces import ListWorkspacesService

    service = ListWorkspacesService.from_directory()
    listing = service.run()
    return CommandResult(exit_code=ExitCode.OK, stdout=listing.render_lines())


def _status_handler(args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio status <target>`` (E3-S1 T8).

    Thin handler delegating to
    :class:`~ramalio.core.status.GetWorkspaceStatusService`.  A missing
    workspace is a successful diagnostic result (state MISSING), not an
    operational error (R15).
    """

    from .core.status import GetWorkspaceStatusService

    service = GetWorkspaceStatusService.from_directory()
    status = service.run(args.target)
    return CommandResult(exit_code=ExitCode.OK, stdout=status.render_lines())


def _start_handler(args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio start <target>`` (E3-S2 T8).

    Delegates to
    :class:`~ramalio.core.startstop.StartWorkspaceService`.  In a
    Git-only project this is a successful no-op that preserves the workspace.
    """

    from .core.startstop import StartWorkspaceService

    service = StartWorkspaceService.from_directory()
    outcome = service.run(args.target)
    return _maybe_open(
        args, target=outcome.target, worktree_path=outcome.workspace_path,
        primary=outcome.render_lines(),
    )


def _stop_handler(args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio stop <target>`` (E3-S2 T8).

    Delegates to
    :class:`~ramalio.core.startstop.StopWorkspaceService`.  In a Git-only
    project this is a successful no-op that never touches worktree, branch or
    local work.
    """

    from .core.startstop import StopWorkspaceService

    service = StopWorkspaceService.from_directory()
    outcome = service.run(args.target)
    return CommandResult(exit_code=ExitCode.OK, stdout=outcome.render_lines())


def _doctor_handler(_args: argparse.Namespace) -> CommandResult:
    """Handle ``ramalio doctor`` (E3-S3 T11).

    Delegates to :class:`~ramalio.core.doctor.DoctorService`.  The
    aggregated verdict maps to the exit code (FAIL -> non-zero; PASS/WARN -> 0);
    the report is rendered on stdout.  Read-only: no mutations or network.
    """

    from .core.doctor import DoctorService

    report = DoctorService.from_directory().run()
    return CommandResult(exit_code=report.exit_code, stdout=report.render_lines())


def default_handlers() -> dict[str, Handler]:
    """Return handlers for the E0 command surface.

    Later specs can replace individual entries without changing parser or render
    contracts.
    """

    handlers: dict[str, Handler] = {
        command: _placeholder_handler(command) for command in PUBLIC_COMMANDS
    }
    # E2-S1 replaces the reserved `init` placeholder with the real handler.
    handlers["init"] = _init_handler
    # E2-S2 replaces the reserved `adopt` placeholder with the real handler.
    handlers["adopt"] = _adopt_handler
    # E2-S3 replaces the reserved `destroy` placeholder with the real handler.
    handlers["destroy"] = _destroy_handler
    # E3-S0 replaces the reserved `list` placeholder with the real handler.
    handlers["list"] = _list_handler
    # E3-S1 replaces the reserved `status` placeholder with the real handler.
    handlers["status"] = _status_handler
    # E3-S2 replaces the reserved `start`/`stop` placeholders.
    handlers["start"] = _start_handler
    handlers["stop"] = _stop_handler
    # E3-S3 replaces the reserved `doctor` placeholder with the real handler.
    handlers["doctor"] = _doctor_handler
    return handlers


def dispatch(
    args: argparse.Namespace,
    handlers: Mapping[str, Handler] | None = None,
) -> CommandResult:
    """Dispatch parsed arguments to one handler and return its result."""

    registry = default_handlers() if handlers is None else handlers
    command = getattr(args, "_handler_name", None)

    if not command:
        raise UsageError("a command is required")

    handler = registry.get(command)
    if handler is None:
        raise UsageError(f"no handler registered for command '{command}'")

    result = handler(args)
    if not isinstance(result, CommandResult):
        raise TypeError(f"handler for '{command}' must return CommandResult")
    return result


def execute(
    argv: Sequence[str] | None = None,
    *,
    handlers: Mapping[str, Handler] | None = None,
) -> CommandResult:
    """Parse and execute explicit arguments without rendering the result.

    ``--help`` and ``--version`` retain argparse's normal ``SystemExit``
    behavior and are intentionally handled only by :func:`main`.
    """

    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return dispatch(args, handlers)


def _normalized_line(text: str | None) -> str:
    """Normalize non-empty wrapper output to exactly one logical final newline."""

    if text is None or text == "":
        return ""
    return text.rstrip("\r\n") + "\n"


def render_result(result: CommandResult, *, stdout: TextIO, stderr: TextIO) -> int:
    """Render a command result exactly once to its declared channels."""

    out = _normalized_line(result.stdout)
    err = _normalized_line(result.stderr)
    if out:
        stdout.write(out)
    if err:
        stderr.write(err)
    return result.code


def _render_expected_error(error: RamalioError, *, stderr: TextIO) -> int:
    stderr.write(_normalized_line(f"error: {error}"))
    return int(error.exit_code)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    handlers: Mapping[str, Handler] | None = None,
) -> int:
    """CLI entry point.

    Explicit streams and handlers make the wrapper unit-testable while normal
    console execution still uses the process streams.
    """

    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr

    try:
        # argparse writes help/version itself. Redirecting here keeps explicit
        # test streams authoritative without teaching domain handlers to print.
        with redirect_stdout(out), redirect_stderr(err):
            result = execute(argv, handlers=handlers)
    except SystemExit as exc:
        # argparse uses SystemExit for normal help/version. Preserve its code and
        # never misclassify it as INTERNAL_ERROR.
        code = exc.code
        return int(code) if isinstance(code, int) else int(ExitCode.OK)
    except RamalioError as exc:
        return _render_expected_error(exc, stderr=err)
    except Exception:
        # Stable public failure contract: no traceback by default.
        err.write(_normalized_line("error: unexpected internal error"))
        return int(ExitCode.INTERNAL_ERROR)

    return render_result(result, stdout=out, stderr=err)


if __name__ == "__main__":  # pragma: no cover - console-script entry point is primary
    raise SystemExit(main())
