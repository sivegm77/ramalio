"""Composer dependency provider for the bootstrap capability (E10-S2).

The executable is fixed ``composer`` (R2): the TOML only controls ``arguments``,
never the executable.  Two executors are supported:

* ``host`` — runs ``composer`` on the host via the central
  :class:`SafeProcessRunner` (argv-only, shell=False, controlled env) with the
  worktree as cwd (R3);
* ``runtime`` — runs the same argv inside a runtime service through the E10-S1
  :class:`RuntimeCommandExecutor`, never importing Docker Compose (R4).

Before installing, each ``writable_paths`` entry is probed for create+delete
with the SAME identity/executor that will run Composer (R5).  After installing,
every declared artifact is validated on the worktree filesystem (R7).
"""

from __future__ import annotations

import os
from pathlib import Path

from ...core.errors import (
    BootstrapProviderFailedError,
    BootstrapReadinessFailedError,
    CapabilityConfigInvalidError,
)
from ...security import (
    CommandSpec,
    PathBoundaryError,
    SafeProcessRunner,
    redact_diagnostic,
    resolve_within_directory,
)
from .models import (
    ArtifactKind,
    BootstrapConfig,
    EXECUTOR_HOST,
    EXECUTOR_RUNTIME,
    RUNTIME_USER_HOST,
)

# The provider's fixed executable (R2): never overridable from the TOML.
COMPOSER_EXECUTABLE = "composer"

# A fixed, product-owned probe script token used only for the runtime writable
# probe: create then delete a marker file.  It is a constant of the product, not
# text from the TOML (R5, §8 security).
_PROBE_MARKER = ".ramalio-writable-probe"


class ComposerProvider:
    """Run Composer + readiness for a bootstrap execution (E10-S2)."""

    provider_name = "composer"

    def __init__(
        self,
        config: BootstrapConfig,
        *,
        worktree_path: Path,
        runner: SafeProcessRunner | None = None,
    ) -> None:
        self._config = config
        self._worktree = worktree_path
        self._runner = runner or SafeProcessRunner()

    # --- environment ------------------------------------------------------

    def _explicit_env(self) -> dict[str, str]:
        """Build the explicit, non-secret environment for Composer (R3).

        Starts from the declared ``environment`` table, then overlays only the
        ``pass_env`` allowlist values present in the host environment (E9-S3
        rules): names, never inline values, and a missing name is simply not
        forwarded.
        """

        env: dict[str, str] = dict(self._config.environment)
        for name in self._config.pass_env:
            value = os.environ.get(name)
            if value is not None:
                env[name] = value
        return env

    def _argv(self) -> tuple[str, ...]:
        return (COMPOSER_EXECUTABLE, *self._config.arguments)

    # --- host executor ----------------------------------------------------

    def _run_host(self) -> None:
        """Run Composer on the host with the worktree as cwd (R3/R6)."""

        spec = CommandSpec(
            argv=self._argv(),
            cwd=self._worktree,
            env=self._explicit_env(),
        )
        result = self._runner.run(spec)
        if result.returncode != 0:
            raise BootstrapProviderFailedError(
                "composer install failed on host: "
                f"{redact_diagnostic(result.stderr)}",
                changed=None,
                resource_identity="composer",
                compensation_available=False,
            )

    def _probe_host(self) -> None:
        """Probe each writable path on the host filesystem directly (R5).

        Resolves each declared relative path inside the worktree and verifies a
        create+delete round-trip.  A failure is a readiness failure, not a
        Composer failure.

        The resolved candidate MUST stay inside the worktree: a symlink at or
        under ``rel`` that points outside the worktree can never authorize a
        write outside it (E7-S2, audit H2).  Rejecting ``..``/absolute paths at
        config time is not enough; the real filesystem target must be checked
        too, because a symlink is invisible to string-level validation.
        """

        for rel in self._config.writable_paths:
            try:
                target = resolve_within_directory(self._worktree, rel)
            except PathBoundaryError as exc:
                raise BootstrapReadinessFailedError(
                    f"writable probe rejected for '{rel}': {exc}"
                ) from exc
            marker = target / _PROBE_MARKER
            try:
                target.mkdir(parents=True, exist_ok=True)
                # Re-check after mkdir: a symlink could have been swapped in
                # concurrently, or `rel` itself could resolve to a symlink whose
                # target only now exists. Re-resolving keeps the guarantee that
                # the marker write always lands inside the worktree.
                target = resolve_within_directory(self._worktree, rel)
                marker = target / _PROBE_MARKER
                marker.write_text("probe", encoding="utf-8")
                marker.unlink()
            except OSError as exc:
                raise BootstrapReadinessFailedError(
                    f"writable probe failed for '{rel}': {exc}"
                ) from exc
            except PathBoundaryError as exc:
                raise BootstrapReadinessFailedError(
                    f"writable probe rejected for '{rel}': {exc}"
                ) from exc

    # --- runtime executor -------------------------------------------------

    def _run_runtime(self, executor, scope, workspace) -> None:
        """Run Composer inside the runtime service (R4)."""

        from ...capabilities.runtime.base import RuntimeExecRequest

        request = RuntimeExecRequest(
            service=self._config.runtime_service,
            argv=self._argv(),
            env=self._explicit_env(),
            user=self._resolve_runtime_user(),
            workdir=self._config.runtime_workdir,
        )
        result = executor.exec(scope, workspace, request)
        if result.returncode != 0:
            raise BootstrapProviderFailedError(
                "composer install failed in runtime: "
                f"{redact_diagnostic(_safe_decode(result.stderr))}",
                changed=None,
                resource_identity="composer",
                compensation_available=False,
            )

    def _probe_runtime(self, executor, scope, workspace) -> None:
        """Probe writable paths inside the runtime via structured argv (R5, §8).

        Uses two independent, structured requests — ``touch -- <marker>`` then
        ``rm -- <marker>`` — never a shell.  ``<marker>`` (derived from the
        project-declared ``rel``) is passed as a single argv element, so shell
        metacharacters in the TOML value (``;``, ``$()``, backticks, spaces)
        stay literal text and are never interpreted (audit H1).  No script or
        shell text originates from the TOML.
        """

        from ...capabilities.runtime.base import RuntimeExecRequest

        for rel in self._config.writable_paths:
            marker = f"{rel.rstrip('/')}/{_PROBE_MARKER}"
            base_kwargs = dict(
                service=self._config.runtime_service,
                env=self._explicit_env(),
                user=self._resolve_runtime_user(),
                workdir=self._config.runtime_workdir,
            )
            touch_request = RuntimeExecRequest(
                argv=("touch", "--", marker), **base_kwargs
            )
            result = executor.exec(scope, workspace, touch_request)
            if result.returncode != 0:
                raise BootstrapReadinessFailedError(
                    f"writable probe failed for '{rel}' inside runtime service "
                    f"'{self._config.runtime_service}'"
                )
            rm_request = RuntimeExecRequest(
                argv=("rm", "--", marker), **base_kwargs
            )
            result = executor.exec(scope, workspace, rm_request)
            if result.returncode != 0:
                raise BootstrapReadinessFailedError(
                    f"writable probe cleanup failed for '{rel}' inside runtime "
                    f"service '{self._config.runtime_service}'"
                )

    def _resolve_runtime_user(self) -> str | None:
        """Resolve ``runtime_user`` to a concrete uid:gid when 'host' (R4).

        ``runtime_user="host"`` maps to ``<host uid>:<host gid>``; no other
        aliases are supported in E10.
        """

        if self._config.runtime_user == RUNTIME_USER_HOST:
            try:
                return f"{os.getuid()}:{os.getgid()}"
            except AttributeError:  # pragma: no cover - non-POSIX
                return None
        return self._config.runtime_user

    # --- artifact readiness ----------------------------------------------

    def _validate_artifacts(self) -> None:
        """Validate every declared artifact on the worktree filesystem (R7).

        The resolved artifact path MUST stay inside the worktree (audit H2): a
        symlink at or under ``artifact.path`` pointing outside can never satisfy
        readiness by referencing a file outside the boundary.
        """

        for artifact in self._config.artifacts:
            try:
                path = resolve_within_directory(self._worktree, artifact.path)
            except PathBoundaryError as exc:
                raise BootstrapReadinessFailedError(
                    f"required artifact '{artifact.path}' escapes the worktree "
                    f"boundary: {exc}"
                ) from exc
            if artifact.kind is ArtifactKind.FILE:
                ok = path.is_file()
                what = "a regular file"
            elif artifact.kind is ArtifactKind.DIRECTORY:
                ok = path.is_dir()
                what = "a directory"
            else:  # EXECUTABLE
                ok = path.is_file() and os.access(path, os.X_OK)
                what = "an executable file"
            if not ok:
                raise BootstrapReadinessFailedError(
                    f"required artifact '{artifact.path}' is not {what}"
                )

    # --- orchestration ----------------------------------------------------

    def provision(self, *, executor=None, scope=None, workspace=None) -> None:
        """Run writable probe -> Composer -> artifact readiness (R5/R6/R7/R8).

        For the runtime executor, ``executor``/``scope``/``workspace`` are
        provided by the capability.  Composer runs only after a successful
        writable probe; artifacts are validated only after Composer succeeds.
        """

        if self._config.executor == EXECUTOR_HOST:
            self._probe_host()
            self._run_host()
        else:  # EXECUTOR_RUNTIME
            if executor is None:
                raise CapabilityConfigInvalidError(
                    "bootstrap: executor='runtime' requires a runtime that "
                    "implements command execution"
                )
            self._probe_runtime(executor, scope, workspace)
            self._run_runtime(executor, scope, workspace)

        # Readiness is evaluated after mutation regardless of executor (R7).
        self._validate_artifacts()

    def readiness_ok(self) -> bool:
        """Whether declared artifacts are satisfied, without mutating (R10).

        Used by ``status`` to derive READY/DEGRADED for a target without
        installing anything.  A boundary escape (audit H2) is treated as
        "not ready" rather than raised, since this is a read-only status probe.
        """

        for artifact in self._config.artifacts:
            try:
                path = resolve_within_directory(self._worktree, artifact.path)
            except PathBoundaryError:
                return False
            if artifact.kind is ArtifactKind.FILE and not path.is_file():
                return False
            if artifact.kind is ArtifactKind.DIRECTORY and not path.is_dir():
                return False
            if artifact.kind is ArtifactKind.EXECUTABLE and not (
                path.is_file() and os.access(path, os.X_OK)
            ):
                return False
        return True


def _safe_decode(raw: object) -> str:
    """Decode bytes stderr for redaction without raising on invalid utf-8."""

    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw) if raw is not None else ""
