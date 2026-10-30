"""Process launch, identity, inspection and termination (E4-S2).

A managed process belongs to exactly one target (INV-01) and is only ever acted
upon when its ownership can be verified via a fingerprint that combines the PID
with the process start time, defeating PID reuse (7.3, INV-03, R6/R11).

Administrative metadata lives outside the versioned repository, namespaced by
project + target, and never contains secrets (R7, 7.2).  On non-Linux platforms
where a start-time fingerprint is unavailable, ownership verification fails
closed rather than risk signaling the wrong process.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from ...core.errors import (
    ProcessOperationFailedError,
    ProcessOwnershipMismatchError,
)
from .models import ProcessItem


def _state_root() -> Path:
    """Return the base directory for non-versioned administrative state (7.2)."""

    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ramalio"


def _project_id(repository_root: Path) -> str:
    """Stable, filesystem-safe identifier for a project root."""

    digest = hashlib.sha256(str(repository_root.resolve()).encode()).hexdigest()
    return digest[:16]


def _read_start_time(pid: int) -> str | None:
    """Return a portable-ish process start marker, or ``None`` if unavailable.

    On Linux, field 22 of ``/proc/<pid>/stat`` is the process start time in
    clock ticks since boot; combined with the PID it is a strong fingerprint.
    Returns ``None`` when it cannot be read (process gone or non-Linux).
    """

    stat_path = Path(f"/proc/{pid}/stat")
    try:
        raw = stat_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # The comm field may contain spaces/parentheses; split on the last ')'.
    try:
        after = raw[raw.rindex(")") + 2 :]
        fields = after.split()
        # starttime is field 22 overall; after comm it is index 19.
        return fields[19]
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # exists but not ours to signal
        return True
    return True


@dataclass(frozen=True, slots=True)
class ProcessMetadata:
    """Persisted operational metadata for one managed process (R6)."""

    target: str
    process_name: str
    pid: int
    start_time: str | None
    cwd: str


class ProcessMetadataStore:
    """Reads/writes per-project, per-target process metadata (R7, 7.2).

    Never stores secrets; only operational identity for ownership checks.
    """

    def __init__(self, repository_root: Path, target: str, *, base: Path | None = None) -> None:
        root = base if base is not None else _state_root()
        self._dir = (
            root
            / _project_id(repository_root)
            / target
            / "processes"
        )

    def _path(self, process_name: str) -> Path:
        return self._dir / f"{process_name}.json"

    def load(self, process_name: str) -> ProcessMetadata | None:
        path = self._path(process_name)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except OSError:
            return None
        except json.JSONDecodeError:  # pragma: no cover - defensive
            return None
        return ProcessMetadata(
            target=raw.get("target", ""),
            process_name=raw.get("process_name", process_name),
            pid=int(raw.get("pid", -1)),
            start_time=raw.get("start_time"),
            cwd=raw.get("cwd", "."),
        )

    def save(self, metadata: ProcessMetadata) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(metadata.process_name)
        path.write_text(json.dumps(asdict(metadata)), encoding="utf-8")
        try:
            path.chmod(0o600)  # E7-S2 R16
        except OSError:  # pragma: no cover - best effort
            pass

    def delete(self, process_name: str) -> None:
        try:
            self._path(process_name).unlink()
        except OSError:
            pass

    @property
    def directory(self) -> Path:
        return self._dir


class ProcessInspector:
    """Determines whether a recorded process is still the owned one (7.3)."""

    def owns(self, metadata: ProcessMetadata) -> bool:
        """Return whether the recorded PID still identifies the owned process.

        Ownership requires the PID to be alive *and* its current start-time
        fingerprint to match the recorded one.  If the recorded fingerprint is
        missing or cannot be recomputed, ownership cannot be confirmed and this
        returns ``False`` (fail closed, INV-03).
        """

        if metadata.pid <= 0:
            return False
        if not _pid_alive(metadata.pid):
            return False
        current = _read_start_time(metadata.pid)
        if metadata.start_time is None or current is None:
            return False
        return current == metadata.start_time


class ProcessLauncher:
    """Launches a managed process with argv/cwd/env (R8)."""

    def __init__(self, worktree_path: Path) -> None:
        self._worktree = worktree_path

    def launch(self, item: ProcessItem) -> ProcessMetadata:
        """Start ``item`` and return verifiable metadata (R6/R8).

        stdout/stderr are redirected to per-process log files so the child never
        blocks the parent (R19).  Metadata is only meaningful once a start-time
        fingerprint is captured.
        """

        cwd = (self._worktree / item.cwd).resolve()
        if not cwd.exists():
            raise ProcessOperationFailedError(
                f"process '{item.name}': cwd {cwd} does not exist"
            )

        # E7-S2 R6/R7/R13: launch through the central SafeProcessRunner
        # (argv-only, shell=False).  The runner applies the controlled base
        # environment and overlays only the process item's explicit env, so
        # unrelated host variables never leak in.
        from ...security import CommandSpec, SafeProcessRunner

        log_dir = cwd / ".ramalio-logs"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            stdout = open(log_dir / f"{item.name}.log", "ab")  # noqa: SIM115
        except OSError as exc:
            raise ProcessOperationFailedError(
                f"process '{item.name}': cannot open log file: {exc}"
            ) from exc

        try:
            proc = SafeProcessRunner().popen(
                CommandSpec(
                    argv=tuple(item.command),
                    cwd=cwd,
                    env=dict(item.environment),
                ),
                stdout=stdout,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            stdout.close()
            raise ProcessOperationFailedError(
                f"process '{item.name}': failed to launch {item.command!r}: {exc}"
            ) from exc
        finally:
            # The child inherited the fd; the parent copy can be closed.
            try:
                stdout.close()
            except OSError:  # pragma: no cover
                pass

        start_time = _read_start_time(proc.pid)
        return ProcessMetadata(
            target="",  # filled by the caller which knows the target
            process_name=item.name,
            pid=proc.pid,
            start_time=start_time,
            cwd=str(cwd),
        )


class ProcessTerminator:
    """Terminates only owned processes (R10-R12, INV-03)."""

    def __init__(self, inspector: ProcessInspector | None = None) -> None:
        self._inspector = inspector or ProcessInspector()

    def terminate(self, metadata: ProcessMetadata, *, timeout: float) -> None:
        """Terminate the owned process gracefully (R10).

        Verifies ownership first (R11): if the PID no longer identifies the
        recorded process, raises :class:`ProcessOwnershipMismatchError` and
        sends no signal.  Sends SIGTERM, waits up to ``timeout``, and escalates
        to SIGKILL only if ownership still holds (R12).
        """

        if not self._inspector.owns(metadata):
            raise ProcessOwnershipMismatchError(
                f"process '{metadata.process_name}' (pid {metadata.pid}) can no "
                "longer be verified as owned; refusing to signal it"
            )

        try:
            os.kill(metadata.pid, signal.SIGTERM)
        except ProcessLookupError:
            return  # already gone
        except PermissionError as exc:  # pragma: no cover - environment dependent
            raise ProcessOperationFailedError(
                f"process '{metadata.process_name}': not permitted to signal "
                f"pid {metadata.pid}: {exc}"
            ) from exc

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _pid_alive(metadata.pid):
                return
            time.sleep(0.05)

        # Escalate only if we still own it (R12).
        if self._inspector.owns(metadata):
            try:
                os.kill(metadata.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
