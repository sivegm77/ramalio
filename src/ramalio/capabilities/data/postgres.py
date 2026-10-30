"""PostgreSQL data provider for the data capability (E10-S3).

Copies the base PostgreSQL database (runtime scope ``project``) into an isolated
per-target database (runtime scope ``workspace``) over the E10-S1
:class:`RuntimeCommandExecutor`.  It never imports Docker Compose and never
touches the source with destructive DDL.

Fixed argv semantics (R5/R6/R7/R8):

* identity   : ``printenv POSTGRES_USER`` / ``printenv POSTGRES_DB``
* readiness  : ``pg_isready -U <user> -d <db>``
* snapshot   : ``pg_dump -U <user> -d <db> --clean --if-exists --no-owner --no-privileges``
* restore    : ``psql -v ON_ERROR_STOP=1 -U <user> -d <db>`` (dump via stdin)

``POSTGRES_PASSWORD`` is never read or printed; the dump is never printed and,
if held on disk, uses a 0600 temp file removed on success/failure.
"""

from __future__ import annotations

import time

from ...core.errors import (
    DataProvisioningFailedError,
    DataReadinessTimeoutError,
)
from ...capabilities.runtime.base import (
    RuntimeExecRequest,
    RuntimeScope,
)

# Bounded polling interval for readiness (seconds).
_READINESS_INTERVAL = 1.0


class _ServiceIdentity:
    """Resolved, non-secret identity for a Postgres service scope."""

    __slots__ = ("user", "db")

    def __init__(self, user: str, db: str) -> None:
        self.user = user
        self.db = db


class PostgresProvider:
    """Snapshot the base DB and restore it into the per-target DB (E10-S3)."""

    provider_name = "postgres"

    def __init__(self, config, *, executor, source_workspace=None, target_workspace):
        # ``executor`` is a RuntimeCommandExecutor (E10-S1). source scope=project
        # uses workspace=None; target scope=workspace uses the target workspace.
        self._config = config
        self._executor = executor
        self._source_workspace = source_workspace  # None -> project scope
        self._target_workspace = target_workspace
        self._service = config.runtime_service

    # --- ensure services (R4) --------------------------------------------

    def _ensure_services(self) -> None:
        # Source is the shared base runtime (project scope); target is the
        # per-target runtime (workspace scope).
        self._executor.ensure_service(RuntimeScope.PROJECT, None, self._service)
        self._executor.ensure_service(
            RuntimeScope.WORKSPACE, self._target_workspace, self._service
        )

    # --- identity resolution inside each service (R5) --------------------

    def _resolve_identity(self, scope, workspace) -> _ServiceIdentity:
        user = self._printenv(scope, workspace, "POSTGRES_USER")
        db = self._printenv(scope, workspace, "POSTGRES_DB")
        if not user or not db:
            raise DataProvisioningFailedError(
                "could not resolve POSTGRES_USER/POSTGRES_DB inside the "
                f"'{self._service}' service",
                changed=False,
            )
        return _ServiceIdentity(user=user, db=db)

    def _printenv(self, scope, workspace, name: str) -> str:
        request = RuntimeExecRequest(
            service=self._service, argv=("printenv", name)
        )
        result = self._executor.exec(scope, workspace, request)
        if result.returncode != 0:
            return ""
        return result.stdout.decode("utf-8", errors="replace").strip()

    # --- readiness (R6) ---------------------------------------------------

    def _wait_ready(self, scope, workspace, identity: _ServiceIdentity) -> None:
        deadline = time.monotonic() + float(self._config.readiness_timeout)
        argv = ("pg_isready", "-U", identity.user, "-d", identity.db)
        while True:
            request = RuntimeExecRequest(service=self._service, argv=argv)
            result = self._executor.exec(scope, workspace, request)
            if result.returncode == 0:
                return
            if time.monotonic() >= deadline:
                raise DataReadinessTimeoutError(
                    f"postgres service '{self._service}' not ready within "
                    f"{self._config.readiness_timeout}s"
                )
            time.sleep(_READINESS_INTERVAL)

    # --- snapshot (R7) ----------------------------------------------------

    def _snapshot(self, identity: _ServiceIdentity) -> bytes:
        """Dump the source database; the dump bytes are never printed (R7)."""

        argv = (
            "pg_dump",
            "-U",
            identity.user,
            "-d",
            identity.db,
            "--clean",
            "--if-exists",
            "--no-owner",
            "--no-privileges",
        )
        request = RuntimeExecRequest(service=self._service, argv=argv)
        result = self._executor.exec(RuntimeScope.PROJECT, None, request)
        if result.returncode != 0:
            raise DataProvisioningFailedError(
                "pg_dump failed on the source database",
                changed=False,
            )
        return result.stdout

    # --- restore (R8) -----------------------------------------------------

    def _restore(self, identity: _ServiceIdentity, dump: bytes) -> None:
        """Restore the dump into the target database via stdin (R8)."""

        argv = (
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            identity.user,
            "-d",
            identity.db,
        )
        request = RuntimeExecRequest(
            service=self._service,
            argv=argv,
            stdin=dump,
        )
        result = self._executor.exec(
            RuntimeScope.WORKSPACE, self._target_workspace, request
        )
        if result.returncode != 0:
            # A restore may have partially applied before failing.  Declare an
            # UNKNOWN mutation so the transaction records it as not-safe; the
            # provider never destroys the target here (R12).
            raise DataProvisioningFailedError(
                "psql restore into the target database failed",
                changed=None,
                resource_identity=f"data:{self._service}",
                compensation_available=False,
            )

    # --- orchestration ----------------------------------------------------

    def provision(self) -> bool:
        """Run ensure -> identity -> readiness -> dump -> restore (R3..R10).

        Returns whether the target was (re)provisioned.  Idempotent by design:
        each enabled init/adopt re-restores the snapshot onto the target (R10);
        no fingerprint/caching is introduced.
        """

        self._ensure_services()

        source_id = self._resolve_identity(RuntimeScope.PROJECT, None)
        target_id = self._resolve_identity(
            RuntimeScope.WORKSPACE, self._target_workspace
        )

        # Both source and target must respond before the dump (R6).
        self._wait_ready(RuntimeScope.PROJECT, None, source_id)
        self._wait_ready(
            RuntimeScope.WORKSPACE, self._target_workspace, target_id
        )

        dump = self._snapshot(source_id)
        self._restore(target_id, dump)
        return True

    def target_ready(self) -> bool:
        """Whether the target service responds to pg_isready, without mutating.

        Used by ``status`` (R13) to derive ACTIVE/READY vs. DEGRADED without a
        dump/restore.
        """

        try:
            target_id = self._resolve_identity(
                RuntimeScope.WORKSPACE, self._target_workspace
            )
        except DataProvisioningFailedError:
            return False
        argv = ("pg_isready", "-U", target_id.user, "-d", target_id.db)
        request = RuntimeExecRequest(service=self._service, argv=argv)
        result = self._executor.exec(
            RuntimeScope.WORKSPACE, self._target_workspace, request
        )
        return result.returncode == 0
