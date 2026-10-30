"""Safe Git command runner (E2-S0 R12, R13).

This is the only place in the product that spawns the ``git`` process.  Every
command:

* is passed as an ``argv`` list, never a shell string (no shell injection);
* runs with an explicit ``cwd``;
* captures exit code, stdout and stderr;
* applies a bounded timeout.

Callers receive a typed :class:`GitCommandOutput`, never raw stdout, so they do
not have to interpret subprocess internals (INV-06, R13).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import GitCommandError, OperationError

# Bounded default timeout for local, read-only Git queries.  E2-S0 never
# contacts a remote (R14), so local queries must complete quickly; the timeout
# is a guard against a stuck subprocess rather than a network budget.
DEFAULT_TIMEOUT_SECONDS: float = 30.0


@dataclass(frozen=True, slots=True)
class GitCommandOutput:
    """Captured result of a single Git invocation (R13).

    ``ok`` is the common success predicate; ``args`` keeps the argv (without the
    leading executable) for diagnostics.
    """

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Whether the command exited successfully."""

        return self.returncode == 0


def _locate_git() -> str:
    """Locate the ``git`` executable or fail with an operation error."""

    git = shutil.which("git")
    if git is None:
        raise OperationError("git executable was not found on PATH")
    return git


class GitRunner:
    """Execute read-only Git commands against a fixed working directory (R12).

    A runner is bound to a ``cwd`` so callers cannot accidentally target another
    repository.  It never builds shell strings and never enables network access
    by itself; the commands issued by the boundary are all local queries (R14).
    """

    def __init__(
        self,
        cwd: Path | str,
        *,
        git_executable: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._cwd = Path(cwd)
        self._git = git_executable if git_executable is not None else _locate_git()
        self._timeout = timeout

    @property
    def cwd(self) -> Path:
        return self._cwd

    def run(
        self, *args: str, check: bool = False, cwd: Path | str | None = None
    ) -> GitCommandOutput:
        """Run ``git <args>`` and capture the result.

        Parameters
        ----------
        args
            Git arguments passed verbatim as argv (never concatenated).
        check
            When ``True``, a non-zero exit raises :class:`GitCommandError` with
            the failing argv and captured stderr (INV-06).  When ``False`` the
            caller inspects :class:`GitCommandOutput` itself, which is the norm
            for existence checks where a non-zero exit is an expected answer.
        cwd
            Optional per-call working directory override, still explicit and
            never a shell string.  Used to query a specific worktree while
            keeping a single runner (so instrumentation sees every command).
            Defaults to the runner's bound ``cwd``.
        """

        argv = tuple(args)
        run_cwd = self._cwd if cwd is None else Path(cwd)
        try:
            completed = subprocess.run(
                [self._git, *argv],
                cwd=str(run_cwd),
                capture_output=True,
                text=True,
                check=False,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing dependent
            raise GitCommandError(
                f"git command timed out after {self._timeout}s: {' '.join(argv)}",
                args=argv,
            ) from exc
        except OSError as exc:  # pragma: no cover - defensive, hard to trigger
            raise GitCommandError(
                f"failed to invoke git: {exc}", args=argv
            ) from exc

        output = GitCommandOutput(
            args=argv,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

        if check and not output.ok:
            raise GitCommandError(
                f"git {' '.join(argv)} failed with exit code {output.returncode}",
                args=argv,
                returncode=output.returncode,
                stderr=output.stderr.strip() or None,
            )

        return output
