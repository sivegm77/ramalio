"""zrok tunnel provider (E6-S3).

Implements the tunnel contract using the ``zrok`` CLI via argv only.  The
provider never reads or logs tokens; credentials come from the user's zrok
environment (R6/R14).  Because zrok assigns a dynamic public URL, the provider
records minimal per-target state (public_url + pid) in a non-versioned,
project-namespaced store owned by the target (R8/R10).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from ...core.errors import TunnelStartFailedError, TunnelStopFailedError
from .base import (
    LocalEndpoint,
    TunnelDoctorCheck,
    TunnelResult,
    TunnelState,
    TunnelWorkspace,
)

PROVIDER_NAME = "zrok"


def _state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ramalio"


def _project_id(repository_root: Path) -> str:
    return hashlib.sha256(str(repository_root.resolve()).encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class TunnelRecord:
    target: str
    pid: int
    public_url: str | None
    # E6-S3 R7/R8: a start-time fingerprint captured at launch. Combined with the
    # PID it lets stop verify the process is still the tunnel this target owns,
    # so a reused PID is never signaled (defeats PID reuse like the processes
    # capability). ``None`` when the platform cannot provide it.
    start_time: str | None = None


class TunnelStateStore:
    """Non-versioned, project+target-namespaced tunnel state (R8/R10)."""

    def __init__(self, repository_root: Path, *, base: Path | None = None) -> None:
        root = base if base is not None else _state_root()
        self._dir = root / _project_id(repository_root) / "tunnels"

    def _path(self, target: str) -> Path:
        safe = hashlib.sha256(target.encode()).hexdigest()[:24]
        return self._dir / f"{safe}.json"

    def load(self, target: str) -> TunnelRecord | None:
        try:
            raw = json.loads(self._path(target).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return TunnelRecord(
            target=raw.get("target", target),
            pid=int(raw.get("pid", -1)),
            public_url=raw.get("public_url"),
            start_time=raw.get("start_time"),
        )

    def save(self, record: TunnelRecord) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(record.target)
        path.write_text(json.dumps(asdict(record)), encoding="utf-8")
        try:
            path.chmod(0o600)  # E7-S2 R16
        except OSError:  # pragma: no cover - best effort
            pass

    def delete(self, target: str) -> None:
        try:
            self._path(target).unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_start_time(pid: int) -> str | None:
    """Return a process start-time marker for PID-reuse defense, or ``None``.

    On Linux, field 22 of ``/proc/<pid>/stat`` is the start time in clock ticks
    since boot; combined with the PID it is a strong fingerprint (E6-S3 R7/R8).
    Returns ``None`` when unavailable (process gone or non-Linux), in which case
    ownership verification fails closed.
    """

    if pid <= 0:
        return None
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        after = raw[raw.rindex(")") + 2 :]
        return after.split()[19]
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return None


def _pid_terminated(pid: int) -> bool:
    """Whether ``pid`` has effectively terminated (dead or a reaped-pending
    zombie), for stop() postcondition checks (E6-S3 R10, P8).

    A process that has exited but not yet been reaped by its parent shows up as
    alive to ``os.kill(pid, 0)`` while its ``/proc/<pid>/stat`` state field is
    ``Z`` (zombie).  Treating a zombie as terminated lets stop() confirm the
    signal worked without waiting on an unreapable child (production zrok runs
    detached with ``start_new_session`` and is reaped by init).

    Fail-closed (audit H7.A): if the PID still answers ``os.kill(pid, 0)`` but
    its ``/proc/<pid>/stat`` cannot be read, we DO NOT know it terminated, so we
    return ``False`` rather than optimistically declaring it gone.  Only a PID
    that no longer exists, or that is observably a zombie, counts as terminated.
    """

    if pid <= 0:
        return True
    if not _pid_alive(pid):
        return True
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        # The process still answers signal 0 but we cannot inspect its state.
        # Fail closed: do not claim termination we cannot prove.
        return False
    try:
        after = raw[raw.rindex(")") + 2 :]
        state = after.split()[0]
    except (ValueError, IndexError):  # pragma: no cover - defensive
        return False
    return state == "Z"


def _terminate_and_verify(pid: int, *, timeout: float) -> bool:
    """Signal ``pid`` with SIGTERM and verify it actually terminates (H7.B/P8).

    Shared by ``stop`` and by the ``start`` fingerprint-failure cleanup path so
    both use one strict "signal -> bounded wait -> verify" sequence instead of a
    fire-and-forget SIGTERM.  Returns ``True`` only when the process is
    demonstrably terminated within ``timeout``; ``False`` if it survives (the
    caller then preserves evidence and reports the failure rather than pretending
    the process was cleaned up).  A PID that is already gone counts as success.
    """

    if pid <= 0:
        return True
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True
    except PermissionError:  # pragma: no cover - defensive
        return False
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _pid_terminated(pid):
            return True
        time.sleep(0.05)
    return _pid_terminated(pid)


class _Ownership(Enum):
    """Tri-state ownership verdict for a recorded tunnel process (audit H5).

    * OWNED     — the PID is alive and its start-time fingerprint matches the
      record: it IS the tunnel this target started.
    * NOT_OWNED — the PID is dead, or alive with a *different* fingerprint (PID
      reuse): it is demonstrably not our tunnel; the stale record is safe to
      drop.
    * UNKNOWN   — the PID is alive but its fingerprint could not be read (record
      never captured one, or ``/proc`` is temporarily unreadable): ownership
      cannot be proven either way, so the process must NOT be signaled and its
      record must NOT be deleted (fail closed, preserve evidence).
    """

    OWNED = "owned"
    NOT_OWNED = "not-owned"
    UNKNOWN = "unknown"


def _tunnel_ownership(record: TunnelRecord) -> _Ownership:
    """Classify ownership of ``record`` into the tri-state verdict (audit H5)."""

    if not _pid_alive(record.pid):
        return _Ownership.NOT_OWNED
    current = _read_start_time(record.pid)
    if current is None:
        # Alive but unverifiable: do not guess in either direction.
        return _Ownership.UNKNOWN
    if record.start_time is None:
        # We can read the current fingerprint but never captured a baseline;
        # we cannot prove it is the same process, so stay UNKNOWN (fail closed).
        return _Ownership.UNKNOWN
    return (
        _Ownership.OWNED
        if current == record.start_time
        else _Ownership.NOT_OWNED
    )


def _owns_tunnel(record: TunnelRecord) -> bool:
    """Whether ``record.pid`` verifiably identifies the tunnel this target
    started (convenience wrapper over :func:`_tunnel_ownership`).

    Only an OWNED verdict returns ``True``; NOT_OWNED and UNKNOWN both return
    ``False`` for callers (like ``start``) that only need to know whether an
    existing tunnel is confirmed active.  Callers that must distinguish
    NOT_OWNED from UNKNOWN (``stop``/``status``) use ``_tunnel_ownership``
    directly (E6-S3 R7/R8/R9).
    """

    return _tunnel_ownership(record) is _Ownership.OWNED


def _ownership_fingerprint_supported() -> bool:
    """Whether this platform provides the PID start-time fingerprint (Linux).

    The zrok provider derives ownership from ``/proc/<pid>/stat`` (Linux only).
    Where it is unavailable (e.g. macOS), ownership cannot be confirmed, so
    ``status`` would report a started tunnel as gone and ``stop`` would refuse to
    signal it.  ``doctor`` surfaces this explicitly rather than leaving a tunnel
    that appears to start but is unmanageable.
    """

    return Path("/proc/self/stat").exists()


class ZrokProvider:
    """Expose a local endpoint via zrok (E6-S3)."""

    def __init__(
        self,
        options=None,
        *,
        executable: str = "zrok",
        state_base: Path | None = None,
        launcher=None,
        stop_timeout: float = 5.0,
    ) -> None:
        self._exe = executable
        self._state_base = state_base
        # launcher(argv, cwd) -> (pid, public_url); injectable for tests.
        self._launcher = launcher
        # E6-S3 R10 (P8): how long stop() waits for graceful termination before
        # reporting a stop failure (kept short and injectable for tests).
        self._stop_timeout = stop_timeout

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def _store(self, workspace: TunnelWorkspace) -> TunnelStateStore:
        root = workspace.repository_root or workspace.worktree_path
        return TunnelStateStore(root, base=self._state_base)

    def doctor(
        self, workspace: TunnelWorkspace | None
    ) -> tuple[TunnelDoctorCheck, ...]:
        available = shutil.which(self._exe) is not None
        supported = _ownership_fingerprint_supported()
        return (
            TunnelDoctorCheck(
                "ZROK_AVAILABLE",
                available,
                "zrok available" if available else "zrok not found on PATH",
            ),
            TunnelDoctorCheck(
                "ZROK_OWNERSHIP_SUPPORTED",
                supported,
                "process ownership fingerprint available (Linux /proc)"
                if supported
                else "zrok ownership fingerprint unavailable on this platform "
                "(requires Linux /proc); tunnel status/stop cannot verify "
                "ownership here",
            ),
        )

    def start(
        self, workspace: TunnelWorkspace, endpoint: LocalEndpoint
    ) -> TunnelResult:
        # E6-S3 R7/R8/R9 (H4): fail closed before launching anything if this
        # platform cannot provide the ownership fingerprint. Starting a tunnel
        # that can never be verified as owned would let it run unmanageable:
        # `status` would report it FAILED immediately and `stop` would refuse
        # to signal it (defense in depth, but here we simply never start it).
        if not _ownership_fingerprint_supported():
            raise TunnelStartFailedError(
                "zrok process ownership requires a Linux /proc filesystem; "
                "this platform cannot verify tunnel ownership, so no tunnel "
                "was started"
            )

        store = self._store(workspace)
        existing = store.load(workspace.target)
        if existing is not None and _owns_tunnel(existing):
            return TunnelResult(
                TunnelState.ACTIVE,
                "tunnel already active",
                existing.public_url,
                changed=False,
            )

        if self._launcher is not None:
            pid, public_url = self._launcher(
                [self._exe, "share", "public", f"{endpoint.host}:{endpoint.port}"],
                str(workspace.worktree_path),
            )
        else:  # pragma: no cover - real zrok not exercised in unit tests
            if shutil.which(self._exe) is None:
                raise TunnelStartFailedError("zrok is not available")
            from ...security import CommandSpec, SafeProcessRunner

            # E7-S2 R6/R7: launch through the central SafeProcessRunner
            # (argv-only, shell=False, controlled environment); zrok is a
            # persistent background process, so popen() is used.
            proc = SafeProcessRunner().popen(
                CommandSpec(
                    argv=(
                        self._exe,
                        "share",
                        "public",
                        f"{endpoint.host}:{endpoint.port}",
                    ),
                    cwd=Path(workspace.worktree_path),
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid, public_url = proc.pid, None

        # E6-S3 R7/R8 (P7): capturing a fingerprint is mandatory. Without it,
        # status would immediately report the tunnel FAILED and stop could never
        # verify ownership. If the fingerprint cannot be captured right after
        # launch, terminate the just-started process and VERIFY it actually died
        # (audit H7.B) before failing closed; never persist an unmanageable
        # record.  If it cannot be verifiably terminated, surface that so the
        # orphaned process is diagnosable rather than silently abandoned.
        start_time = _read_start_time(pid)
        if start_time is None:
            terminated = _terminate_and_verify(pid, timeout=self._stop_timeout)
            if not terminated:
                # Audit H5/H4: the process is still running and unverifiable.
                # Preserve an ORPHANED record (pid, no fingerprint) so the
                # leftover process stays diagnosable, and declare the mutation
                # (changed=True) via the partial-mutation contract so the
                # lifecycle transaction can surface it as an unsafe resource
                # rather than losing it.  ``stop`` will later classify this
                # record UNKNOWN and refuse to blindly signal it.
                store.save(
                    TunnelRecord(
                        target=workspace.target,
                        pid=pid,
                        public_url=public_url,
                        start_time=None,
                    )
                )
                raise TunnelStartFailedError(
                    f"zrok tunnel for '{workspace.target}' started (pid {pid}) "
                    "but its ownership fingerprint could not be captured, and "
                    "the process did not terminate after SIGTERM; an ORPHANED "
                    "record was preserved for diagnosis/manual cleanup",
                    changed=True,
                    resource_identity=f"tunnel:{workspace.target}",
                    compensation_available=False,
                )
            # The just-started process was confirmed terminated: no durable
            # mutation remains, so declare changed=False.
            raise TunnelStartFailedError(
                f"zrok tunnel for '{workspace.target}' started (pid {pid}) but "
                "its ownership fingerprint could not be captured; the process "
                "was signaled and confirmed terminated, and no tunnel state was "
                "persisted",
                changed=False,
            )

        store.save(
            TunnelRecord(
                target=workspace.target,
                pid=pid,
                public_url=public_url,
                start_time=start_time,
            )
        )
        return TunnelResult(
            TunnelState.ACTIVE, "tunnel started", public_url, changed=True
        )

    def stop(self, workspace: TunnelWorkspace) -> TunnelResult:
        store = self._store(workspace)
        record = store.load(workspace.target)
        if record is None:
            return TunnelResult(TunnelState.STOPPED, "no tunnel", changed=False)
        # E6-S3 R9/R10 + audit H5: branch on the tri-state ownership verdict so
        # "not ours" (safe to forget) is never confused with "cannot verify"
        # (must be preserved).
        ownership = _tunnel_ownership(record)

        if ownership is _Ownership.UNKNOWN:
            # Alive but unverifiable: do NOT signal (could be a reused PID) and
            # do NOT delete the record (it is the only evidence of a possibly
            # still-running tunnel).  Fail closed so the state stays diagnosable.
            raise TunnelStopFailedError(
                f"zrok tunnel for '{workspace.target}' (pid {record.pid}) cannot "
                "be verified as owned (process alive but fingerprint "
                "unreadable); refusing to signal it and preserving its state "
                "for diagnosis"
            )

        if ownership is _Ownership.NOT_OWNED:
            # Dead or a reused PID -> nothing of ours to signal; the stale
            # record can be safely removed.  No live tunnel was torn down, so
            # this is not a mutation for ownership purposes (changed=False).
            store.delete(workspace.target)
            return TunnelResult(
                TunnelState.STOPPED, "tunnel stopped", changed=False
            )

        # OWNED: one strict signal -> bounded wait -> verify sequence (H7.B).
        if _terminate_and_verify(record.pid, timeout=self._stop_timeout):
            store.delete(workspace.target)
            return TunnelResult(
                TunnelState.STOPPED, "tunnel stopped", changed=True
            )

        # Still alive after the timeout: do NOT delete the ownership record, so
        # the tunnel stays diagnosable and re-stoppable rather than orphaned.
        raise TunnelStopFailedError(
            f"zrok tunnel for '{workspace.target}' (pid {record.pid}) did not "
            f"terminate within {self._stop_timeout:.1f}s; ownership state was "
            "preserved for diagnosis/retry"
        )

    def status(self, workspace: TunnelWorkspace) -> TunnelResult:
        record = self._store(workspace).load(workspace.target)
        if record is None:
            return TunnelResult(TunnelState.STOPPED, "no tunnel")
        ownership = _tunnel_ownership(record)
        if ownership is _Ownership.OWNED:
            return TunnelResult(TunnelState.ACTIVE, "tunnel active", record.public_url)
        if ownership is _Ownership.UNKNOWN:
            # Alive but unverifiable: report DEGRADED rather than ACTIVE or gone,
            # so operators see a tunnel that needs attention without the tool
            # claiming a state it cannot prove (audit H5).
            return TunnelResult(
                TunnelState.DEGRADED,
                "tunnel process alive but ownership unverifiable",
                record.public_url,
            )
        return TunnelResult(
            TunnelState.FAILED, "tunnel process gone", record.public_url
        )

    def cleanup(self, workspace: TunnelWorkspace) -> TunnelResult:
        # Idempotent: stop covers process termination + state removal (R10).
        return self.stop(workspace)


def make_provider(options) -> ZrokProvider:
    """Factory used by the tunnel provider registry."""

    return ZrokProvider(options)
