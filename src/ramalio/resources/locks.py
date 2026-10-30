"""Granular, cross-process filesystem locks (E7-S1).

Locks protect only resources that genuinely compete (same target/branch/path/
port pool), never a global per-user lock (INV).  The backend is ``fcntl.flock``
over per-key files in a non-versioned state directory: an advisory exclusive
lock is released automatically when the fd closes or the owning process dies,
which gives safe stale recovery for free (R11/R12/R13).

Keys are derived from canonical identity (normalized target/paths), not ambiguous
strings (R6).  When several locks are needed they are acquired in a deterministic
global scope order to avoid deadlocks (R7).
"""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from ..core.errors import LockTimeoutError

DEFAULT_TIMEOUT = 10.0


class LockScope(IntEnum):
    """Lock scopes with a deterministic global acquisition order (R2/R7).

    The integer values define the canonical order in which multiple locks are
    acquired (lower first), preventing deadlocks.
    """

    PROJECT = 0
    TARGET = 1
    BRANCH = 2
    WORKTREE_PATH = 3
    PORT_POOL = 4


def _state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ramalio"


@dataclass(frozen=True, slots=True)
class LockKey:
    """A canonical lock key (R6)."""

    scope: LockScope
    value: str

    def filename(self) -> str:
        digest = hashlib.sha256(self.value.encode()).hexdigest()[:24]
        return f"{self.scope.name.lower()}-{digest}.lock"


@dataclass(frozen=True, slots=True)
class LockInfo:
    """Owner metadata recorded for a held lock (R9)."""

    scope: str
    key: str
    pid: int
    operation: str
    timestamp: float


class LockManager:
    """Acquires/releases cross-process filesystem locks (R1)."""

    def __init__(
        self,
        project_id: str,
        *,
        base: Path | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        root = base if base is not None else _state_root()
        self._dir = root / project_id / "locks"
        self._timeout = timeout

    @classmethod
    def for_repository(
        cls, repository_root: Path, *, base: Path | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> "LockManager":
        pid = hashlib.sha256(str(Path(repository_root).resolve()).encode()).hexdigest()[
            :16
        ]
        return cls(pid, base=base, timeout=timeout)

    @property
    def directory(self) -> Path:
        return self._dir

    @contextmanager
    def acquire(
        self,
        key: LockKey,
        *,
        operation: str,
        timeout: float | None = None,
    ):
        """Acquire an exclusive lock for ``key`` as a context manager (R3/R12).

        Blocks up to ``timeout`` seconds, then raises :class:`LockTimeoutError`
        (R8) without mutating anything.  The lock (and its metadata) is released
        in ``finally`` even on exception, and by the OS if the process dies
        (R11/R12).
        """

        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / key.filename()
        deadline = time.monotonic() + (self._timeout if timeout is None else timeout)

        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EAGAIN, errno.EACCES):
                        raise  # pragma: no cover - unexpected
                    if time.monotonic() >= deadline:
                        raise LockTimeoutError(
                            f"could not acquire {key.scope.name} lock for "
                            f"'{key.value}' within timeout"
                        ) from None
                    time.sleep(0.02)

            # Record owner metadata for diagnostics (R9).
            info = LockInfo(
                scope=key.scope.name,
                key=key.value,
                pid=os.getpid(),
                operation=operation,
                timestamp=time.time(),
            )
            try:
                from dataclasses import asdict

                os.ftruncate(fd, 0)
                os.write(fd, json.dumps(asdict(info)).encode())
                os.fsync(fd)
            except OSError:  # pragma: no cover - metadata is best-effort
                pass

            yield info
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:  # pragma: no cover
                pass
            os.close(fd)

    @contextmanager
    def acquire_all(self, keys: list[LockKey], *, operation: str, timeout: float | None = None):
        """Acquire several locks in deterministic scope order (R7).

        Nesting the context managers guarantees ordered acquisition and reverse
        release.
        """

        ordered = sorted(keys, key=lambda k: (int(k.scope), k.value))
        from contextlib import ExitStack

        with ExitStack() as stack:
            infos = []
            for key in ordered:
                infos.append(
                    stack.enter_context(
                        self.acquire(key, operation=operation, timeout=timeout)
                    )
                )
            yield tuple(infos)

    def read_lock_info(self, key: LockKey) -> LockInfo | None:
        """Read a lock's owner metadata for diagnostics, without locking (R16)."""

        path = self._dir / key.filename()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return LockInfo(
            scope=raw.get("scope", key.scope.name),
            key=raw.get("key", key.value),
            pid=int(raw.get("pid", -1)),
            operation=raw.get("operation", ""),
            timestamp=float(raw.get("timestamp", 0.0)),
        )

    def is_held_by_live_process(self, key: LockKey) -> bool:
        """Best-effort: whether the lock file is currently held (R10).

        Tries a non-blocking acquire; if it fails the lock is held by a live
        process.  Never removes a lock by age alone (R11).
        """

        path = self._dir / key.filename()
        if not path.exists():
            return False
        fd = os.open(path, os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False  # we acquired it -> not held
        except OSError:
            return True
        finally:
            os.close(fd)

    def list_locks(self) -> list[LockInfo]:
        """Return owner metadata for every lock file, read-only (R16).

        Enumerates the lock directory without acquiring or removing anything, so
        ``doctor`` can report active/stale locks without side effects (R16/R11).
        Lock files whose metadata cannot be parsed are still reported with a
        best-effort placeholder so a stale/corrupt lock stays visible (R10).
        """

        infos: list[LockInfo] = []
        if not self._dir.exists():
            return infos
        for path in sorted(self._dir.glob("*.lock")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                infos.append(
                    LockInfo(
                        scope=raw.get("scope", "UNKNOWN"),
                        key=raw.get("key", path.stem),
                        pid=int(raw.get("pid", -1)),
                        operation=raw.get("operation", ""),
                        timestamp=float(raw.get("timestamp", 0.0)),
                    )
                )
            except (OSError, json.JSONDecodeError, ValueError):
                infos.append(
                    LockInfo(
                        scope="UNKNOWN",
                        key=path.stem,
                        pid=-1,
                        operation="",
                        timestamp=0.0,
                    )
                )
        return infos

    def is_pid_alive(self, pid: int) -> bool:
        """Whether ``pid`` is a live process, read-only (R10).

        Used by diagnostics to classify a lock whose recorded owner no longer
        exists as *stale* without removing it (R11).
        """

        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def is_held_by_path(self, path: Path) -> bool:
        """Whether the lock file at ``path`` is currently held by any process.

        Tries a non-blocking ``flock``; failure means the lock is actively held.
        Read-only: it never removes or rewrites the file (R11/R16).  This
        distinguishes a *held* lock from a mere leftover lock *file* (which
        persists on disk after the holder releases it).
        """

        if not path.exists():
            return False
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError:  # pragma: no cover - defensive
            return False
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return False  # acquired it -> not currently held
        except OSError:
            return True
        finally:
            os.close(fd)

    def classify_locks(self) -> list[tuple[LockInfo, bool]]:
        """Return ``(info, held)`` for each lock file, read-only (R10/R16).

        ``held`` reflects whether the OS lock is *actually* held right now (via a
        non-blocking ``flock``), not merely whether a lock *file* exists or whose
        recorded PID happens to still be alive.  This is what ``doctor`` needs to
        avoid reporting a released-but-leftover lock file as an active/stale lock
        (E7-S1 R10/R16).
        """

        classified: list[tuple[LockInfo, bool]] = []
        if not self._dir.exists():
            return classified
        for path in sorted(self._dir.glob("*.lock")):
            held = self.is_held_by_path(path)
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                info = LockInfo(
                    scope=raw.get("scope", "UNKNOWN"),
                    key=raw.get("key", path.stem),
                    pid=int(raw.get("pid", -1)),
                    operation=raw.get("operation", ""),
                    timestamp=float(raw.get("timestamp", 0.0)),
                )
            except (OSError, json.JSONDecodeError, ValueError):
                info = LockInfo(
                    scope="UNKNOWN",
                    key=path.stem,
                    pid=-1,
                    operation="",
                    timestamp=0.0,
                )
            classified.append((info, held))
        return classified
