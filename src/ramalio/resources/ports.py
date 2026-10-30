"""Deterministic per-target port allocation and reservation (E6-S1).

Ports are an optional managed resource that Git does not own.  Reservations live
in a non-versioned, project-namespaced store (never a SiVale-specific global
file, R4/INV).  Allocation is deterministic for a given set of reservations
(R3): a target's preferred candidate is derived from a stable hash of its name
within the configured range, then a linear scan resolves collisions.

External occupancy is detected best-effort by attempting to bind a local socket
(R6); an occupied port is skipped, never killed.  Concurrency hardening (locks)
lands in E7-S1; the store here is single-process safe.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config.models import PortsConfig
from ..core.errors import PortRangeExhaustedError


def _state_root() -> Path:
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "ramalio"


def _project_id(repository_root: Path) -> str:
    digest = hashlib.sha256(str(repository_root.resolve()).encode()).hexdigest()
    return digest[:16]


@dataclass(frozen=True, slots=True)
class PortReservation:
    """A port reserved by a target within a project (R4)."""

    target: str
    port: int
    project_id: str


class PortReservationStore:
    """Non-versioned, project-namespaced reservation store (R4, 7)."""

    def __init__(self, repository_root: Path, *, base: Path | None = None) -> None:
        root = base if base is not None else _state_root()
        self._project_id = _project_id(repository_root)
        self._dir = root / self._project_id / "ports"

    @property
    def project_id(self) -> str:
        return self._project_id

    def _path(self, target: str) -> Path:
        # Namespaced by target; the filename is a safe hash to avoid odd chars.
        safe = hashlib.sha256(target.encode()).hexdigest()[:24]
        return self._dir / f"{safe}.json"

    def load(self, target: str) -> PortReservation | None:
        try:
            raw = json.loads(self._path(target).read_text(encoding="utf-8"))
        except OSError:
            return None
        except json.JSONDecodeError:  # pragma: no cover - defensive
            return None
        return PortReservation(
            target=raw["target"], port=int(raw["port"]), project_id=raw["project_id"]
        )

    def all(self) -> list[PortReservation]:
        reservations: list[PortReservation] = []
        if not self._dir.exists():
            return reservations
        for path in sorted(self._dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                reservations.append(
                    PortReservation(
                        target=raw["target"],
                        port=int(raw["port"]),
                        project_id=raw["project_id"],
                    )
                )
            except (OSError, json.JSONDecodeError, KeyError):  # pragma: no cover
                continue
        return reservations

    def save(self, reservation: PortReservation) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(reservation.target)
        path.write_text(json.dumps(asdict(reservation)), encoding="utf-8")
        # E7-S2 R16: state metadata is user-private.
        try:
            path.chmod(0o600)
        except OSError:  # pragma: no cover - best effort
            pass

    def delete(self, target: str) -> None:
        try:
            self._path(target).unlink()
        except OSError:
            pass


def _port_free_locally(port: int) -> bool:
    """Best-effort check that ``port`` is not in use locally (R6)."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class PortAllocator:
    """Deterministic allocator over a configured range (R3/R5/R6/R7)."""

    def __init__(
        self,
        config: PortsConfig,
        store: PortReservationStore,
        *,
        port_probe=_port_free_locally,
        lock_manager=None,
    ) -> None:
        self._config = config
        self._store = store
        self._probe = port_probe
        self._lock_manager = lock_manager

    def _candidates(self, target: str) -> list[int]:
        """Deterministic candidate order for ``target`` within the range (R3)."""

        size = self._config.size
        start = self._config.start
        digest = hashlib.sha256(target.encode()).hexdigest()
        offset = int(digest, 16) % size
        # Preferred candidate first, then a wrap-around linear scan.
        return [start + ((offset + i) % size) for i in range(size)]

    def reserve(self, target: str) -> PortReservation:
        """Reserve (or reuse) a port for ``target`` (R4/R5/R11).

        Idempotent: an existing reservation for the target is returned as-is
        (R11).  A port reserved by another target is never reused (R5); a port
        occupied by an external process is skipped (R6).  Raises
        :class:`PortRangeExhaustedError` when nothing is free (R7).

        When a lock manager is provided, the scan+reserve critical section is
        protected by a port-pool lock so concurrent allocations never pick the
        same port (E7-S1 R5).
        """

        if self._lock_manager is None:
            return self._reserve_locked(target)

        from .locks import LockKey, LockScope

        pool_key = LockKey(
            LockScope.PORT_POOL,
            f"{self._store.project_id}:{self._config.start}:{self._config.size}",
        )
        with self._lock_manager.acquire(pool_key, operation="port-reserve"):
            return self._reserve_locked(target)

    def _reserve_locked(self, target: str) -> PortReservation:
        existing = self._store.load(target)
        if existing is not None:
            return existing

        taken = {
            r.port: r.target
            for r in self._store.all()
            if r.target != target
        }
        for port in self._candidates(target):
            if port in taken:
                continue  # R5: reserved by another target
            if not self._probe(port):
                continue  # R6: occupied externally
            reservation = PortReservation(
                target=target, port=port, project_id=self._store.project_id
            )
            self._store.save(reservation)
            return reservation

        raise PortRangeExhaustedError(
            f"no free port available in range "
            f"{self._config.start}..{self._config.start + self._config.size - 1} "
            f"for target '{target}'"
        )

    def release(self, target: str) -> bool:
        """Release only the reservation owned by ``target`` (R12).

        Returns whether a reservation was removed.
        """

        if self._store.load(target) is None:
            return False
        self._store.delete(target)
        return True

    def current(self, target: str) -> PortReservation | None:
        return self._store.load(target)
