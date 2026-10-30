"""Docker Compose runtime driver (E6-S2).

An optional runtime driver implementing the E6-S0 contract.  Each target gets a
unique, deterministic Compose project name so worktrees never share Compose
state (INV); commands always carry ``-p <project>`` so they can never affect
another workspace (R11).  Docker is never a core dependency: this driver is only
active when a project selects ``driver = "docker-compose"``.

All Compose invocations are argv lists (never a shell string), keeping execution
injection-free (R5).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import stat as stat_module
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping

from ...core.errors import (
    CapabilityConfigInvalidError,
    RuntimeCleanupFailedError,
    RuntimeStartFailedError,
    RuntimeStopFailedError,
)
from ...security import redact_diagnostic
from .base import (
    RuntimeCommandExecutor,
    RuntimeDoctorCheck,
    RuntimeExecRequest,
    RuntimeExecResult,
    RuntimeResult,
    RuntimeScope,
    RuntimeState,
    RuntimeWorkspace,
)

DRIVER_NAME = "docker-compose"

_DEFAULT_COMPOSE_FILE = "compose.yaml"
_DEFAULT_PROJECT_PATTERN = "{project}-{target}"

# Compose project names must be lowercase and may only contain [a-z0-9_-].
_INVALID_PROJECT_CHARS = re.compile(r"[^a-z0-9_-]+")


def sanitize_project_name(raw: str) -> str:
    """Return a Compose-safe project name (R3)."""

    name = raw.lower()
    name = _INVALID_PROJECT_CHARS.sub("-", name)
    name = name.strip("-_")
    return name or "ramalio"


def _files_identical(a: Path, b: Path) -> bool:
    """Whether two files have identical bytes, without ever printing content.

    Used by ``materialize_env_file`` to decide idempotent no-op vs. conflict
    (audit H3).  Compares in fixed-size chunks so large files are never fully
    loaded into memory or surfaced in diagnostics.
    """

    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        chunk_size = 65536
        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                chunk_a = fa.read(chunk_size)
                chunk_b = fb.read(chunk_size)
                if chunk_a != chunk_b:
                    return False
                if not chunk_a:
                    return True
    except OSError:
        return False


@dataclass(frozen=True, slots=True)
class _EnvFileIdentity:
    """Strong identity of the env file THIS call created (F1-followup).

    A bare ``(st_dev, st_ino)`` pair is not enough to prove that the file at a
    lexical path is still the exact resource this operation created:

    * an inode freed by ``unlink`` can be reused immediately by the next
      regular file created at the same path, so a replacement file may inherit
      the identical ``(st_dev, st_ino)``;
    * a same-inode in-place rewrite would keep the pair unchanged while the
      contents are no longer the ones we wrote.

    This identity therefore also captures the creation/modification timestamps,
    size, and a digest of the exact bytes written. The digest is computed in
    memory only and is NEVER logged or surfaced in diagnostics (INV-08).

    F1.3 (degraded ownership): when the strong identity cannot be captured
    after the file was created AND the immediate cleanup also failed, ownership
    must still be recorded so the mutation is never lost. Such an entry is
    marked ``verified=False``: it records that THIS call created a file at the
    lexical path but could not witness its full identity. Compensation treats a
    degraded entry fail-closed — it retires a regular, non-symlink file at the
    lexical path (best effort) and, if it cannot, surfaces the mutation as an
    inconsistency instead of silently forgetting it (E7-S0 R3/R6, INV-05/06).
    """

    dev: int
    ino: int
    ctime_ns: int
    mtime_ns: int
    size: int
    content_digest: str
    verified: bool = True

    @classmethod
    def from_stat_and_bytes(cls, st, content: bytes) -> "_EnvFileIdentity":
        return cls(
            dev=st.st_dev,
            ino=st.st_ino,
            ctime_ns=st.st_ctime_ns,
            mtime_ns=st.st_mtime_ns,
            size=st.st_size,
            # sha256 of the written bytes; a stable identity witness, never
            # emitted anywhere (used only for equality comparison).
            content_digest=hashlib.sha256(content).hexdigest(),
            verified=True,
        )

    @classmethod
    def unverified(cls) -> "_EnvFileIdentity":
        """A degraded ownership marker (F1.3 fail-closed).

        Recorded when this call created the destination but could neither
        witness the file's strong identity nor retire it immediately. It
        carries no usable identity fields, only the fact that a mutation
        happened and must be compensated/diagnosed later.
        """

        return cls(
            dev=0, ino=0, ctime_ns=0, mtime_ns=0, size=0,
            content_digest="", verified=False,
        )


@dataclass(frozen=True, slots=True)
class _ComposeConfig:
    compose_file: str
    project_pattern: str
    port_env: str | None
    # E10-S1 provisioning options (all defaults are safe/backward-compatible).
    provision_on_init: bool = False
    provision_on_adopt: bool = False
    build_on_provision: bool = False
    base_project_pattern: str = "{project}"
    materialize_env_file: str | None = None
    remove_volumes_on_destroy: bool = False
    # E10-S1 §12 enmienda (audit H5.B): ordered, optional additional Compose
    # layers (e.g. an override file), each added as its own `-f` only when
    # actually present in the worktree (mirrors the legacy harness).
    compose_files: tuple[str, ...] = ()


# All keys DockerComposeDriver accepts (E6-S2 + E10-S1). Unknown keys fail
# closed with CapabilityConfigInvalidError (audit H4): the E10-S1 contract
# explicitly requires "unknown keys stay fail-closed", but the generic
# [capabilities.*] parser deliberately stores everything in ``options`` without
# rejecting unknown names, so this driver-level allowlist is the enforcement
# point.
_KNOWN_OPTIONS = frozenset(
    {
        "driver",
        "compose_file",
        "compose_files",
        "project_pattern",
        "port_env",
        "provision_on_init",
        "provision_on_adopt",
        "build_on_provision",
        "base_project_pattern",
        "materialize_env_file",
        "remove_volumes_on_destroy",
    }
)


def _require_bool(opts: Mapping[str, object], key: str, default: bool) -> bool:
    """Read an optional boolean option, failing closed on a wrong type (E10-S1)."""

    if key not in opts:
        return default
    value = opts[key]
    if not isinstance(value, bool):
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must be a boolean, got {type(value).__name__}"
        )
    return value


def _require_nonempty_str(
    opts: Mapping[str, object], key: str, default: str
) -> str:
    """Read an optional non-empty string option, failing closed (E10-S1)."""

    if key not in opts:
        return default
    value = opts[key]
    if not isinstance(value, str) or not value.strip():
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must be a non-empty string"
        )
    return value


def _optional_relative_path(
    opts: Mapping[str, object], key: str
) -> str | None:
    """Read an optional relative path option, rejecting unsafe values (E10-S1).

    ``materialize_env_file`` must be relative to the repository/worktree root
    and must never be absolute, contain ``..`` segments or a NUL byte, so it can
    never escape the workspace boundary.  Absence means "do not copy".
    """

    if key not in opts or opts[key] is None:
        return None
    value = opts[key]
    if not isinstance(value, str) or not value.strip():
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must be a non-empty relative path"
        )
    if "\x00" in value:
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must not contain a NUL byte"
        )
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or Path(value).is_absolute():
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must be a relative path, not '{value}'"
        )
    if ".." in candidate.parts or ".." in Path(value).parts:
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must not contain '..' segments"
        )
    return value


def _optional_relative_path_list(
    opts: Mapping[str, object], key: str
) -> tuple[str, ...]:
    """Read an optional ordered list of relative paths (E10-S1 §12, audit H5.B).

    Each entry follows the same safety rules as :func:`_optional_relative_path`
    (relative, no absolute/``..``/NUL).  Absence or an empty list means "no
    additional Compose layers".
    """

    if key not in opts or opts[key] is None:
        return ()
    value = opts[key]
    if not isinstance(value, list):
        raise CapabilityConfigInvalidError(
            f"runtime: '{key}' must be a list of relative paths"
        )
    result: list[str] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            raise CapabilityConfigInvalidError(
                f"runtime: '{key}[{index}]' must be a non-empty relative path"
            )
        if "\x00" in entry:
            raise CapabilityConfigInvalidError(
                f"runtime: '{key}[{index}]' must not contain a NUL byte"
            )
        candidate = PurePosixPath(entry)
        if candidate.is_absolute() or Path(entry).is_absolute():
            raise CapabilityConfigInvalidError(
                f"runtime: '{key}[{index}]' must be a relative path, not "
                f"'{entry}'"
            )
        if ".." in candidate.parts or ".." in Path(entry).parts:
            raise CapabilityConfigInvalidError(
                f"runtime: '{key}[{index}]' must not contain '..' segments"
            )
        result.append(entry)
    return tuple(result)


class _DockerRunner:
    """Argv-only adapter over the docker CLI (R5)."""

    def __init__(self, executable: str = "docker") -> None:
        self._exe = executable

    @property
    def available(self) -> bool:
        return shutil.which(self._exe) is not None

    def compose_available(self) -> bool:
        if not self.available:
            return False
        result = self._run("compose", "version")
        return result.returncode == 0

    def _run(
        self, *args: str, cwd: str | None = None, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        # E7-S2 R6/R7/R13: execute through the central SafeProcessRunner
        # (argv-only, shell=False).  The runner starts from the controlled base
        # environment and overlays only the explicit variables the driver
        # derived (e.g. the reserved port), so unrelated host variables never
        # become runtime configuration.
        from pathlib import Path

        from ...security import CommandSpec, SafeProcessRunner

        spec = CommandSpec(
            argv=(self._exe, *args),
            cwd=Path(cwd) if cwd is not None else Path.cwd(),
            env=dict(env) if env else {},
        )
        return SafeProcessRunner().run(spec)

    def compose(
        self,
        project: str,
        compose_file: str,
        *args: str,
        cwd: str,
        env: Mapping[str, str] | None = None,
        extra_files: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess:
        # Always identity-scoped with -p (R11). Additional -f layers (E10-S1
        # §12, audit H5.B) are appended in declared order, after the primary
        # compose_file, mirroring `docker compose -f base -f override ...`.
        f_flags: list[str] = ["-f", compose_file]
        for extra in extra_files:
            f_flags += ["-f", extra]
        return self._run(
            "compose", "-p", project, *f_flags, *args, cwd=cwd, env=env
        )

    def compose_bytes(
        self,
        project: str,
        compose_file: str,
        *args: str,
        cwd: str,
        env: Mapping[str, str] | None = None,
        stdin: bytes | None = None,
        extra_files: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess:
        """Run an identity-scoped Compose command capturing raw bytes (E10-S1 R11).

        Used by runtime command execution where stdout/stderr are opaque
        payloads and an input stream may be piped in.  Still argv-only and
        ``shell=False`` via :class:`SafeProcessRunner`.
        """

        from pathlib import Path

        from ...security import CommandSpec, SafeProcessRunner

        f_flags: list[str] = ["-f", compose_file]
        for extra in extra_files:
            f_flags += ["-f", extra]
        spec = CommandSpec(
            argv=(self._exe, "compose", "-p", project, *f_flags, *args),
            cwd=Path(cwd),
            env=dict(env) if env else {},
        )
        return SafeProcessRunner().run_bytes(spec, stdin=stdin)


class DockerComposeDriver:
    """Runtime driver backed by Docker Compose (E6-S2)."""

    def __init__(
        self,
        options: Mapping[str, object] | None = None,
        *,
        runner: _DockerRunner | None = None,
        project_name: str = "ramalio",
        port_provider=None,
        repository_root: Path | None = None,
    ) -> None:
        opts = dict(options or {})
        # Audit H4: fail closed on any option this driver does not recognize,
        # instead of silently accepting it (the generic capability parser does
        # not reject unknown keys on its own).
        unknown = set(opts) - _KNOWN_OPTIONS
        if unknown:
            raise CapabilityConfigInvalidError(
                "runtime: unknown option(s) for driver 'docker-compose': "
                f"{', '.join(sorted(unknown))}"
            )
        self._config = _ComposeConfig(
            compose_file=str(opts.get("compose_file", _DEFAULT_COMPOSE_FILE)),
            project_pattern=str(opts.get("project_pattern", _DEFAULT_PROJECT_PATTERN)),
            port_env=(
                str(opts["port_env"]) if opts.get("port_env") is not None else None
            ),
            provision_on_init=_require_bool(opts, "provision_on_init", False),
            provision_on_adopt=_require_bool(opts, "provision_on_adopt", False),
            build_on_provision=_require_bool(opts, "build_on_provision", False),
            base_project_pattern=_require_nonempty_str(
                opts, "base_project_pattern", "{project}"
            ),
            materialize_env_file=_optional_relative_path(
                opts, "materialize_env_file"
            ),
            remove_volumes_on_destroy=_require_bool(
                opts, "remove_volumes_on_destroy", False
            ),
            compose_files=_optional_relative_path_list(opts, "compose_files"),
        )
        self._runner = runner or _DockerRunner()
        self._project_name = project_name
        self._port_provider = port_provider
        # Audit H6: repository root lets doctor validate the configured compose
        # file even without a concrete target/worktree.
        self._repository_root = repository_root
        # Audit H3: tracks, per target, whether THIS call materialized (created)
        # the env file, so compensation retires only the file this operation
        # owns and never a preexisting one (E7-S0 R3/R11).
        #
        # F1-followup (identity check): storing a plain bool is not enough —
        # if the lexical path is later replaced by a symlink into another
        # in-worktree file, ``resolve_within_directory`` would resolve to that
        # OTHER file, which then passes ``is_file() and not is_symlink()`` and
        # gets deleted even though it is not the resource this call created.
        #
        # A bare ``(st_dev, st_ino)`` pair is ALSO insufficient: an inode is
        # freed on ``unlink`` and can be reused immediately by the very next
        # regular file created at the same lexical path (observed in the F1
        # regression on some filesystems), so a replacement file could inherit
        # the exact same (dev, ino) and be mistaken for the owned resource.
        # Each entry is therefore a stronger ``_EnvFileIdentity`` capturing
        # device + inode + creation/mtime timestamps + size + an in-memory
        # content digest, all snapshotted at creation time. Compensation
        # recomputes this identity from the lexical path and only unlinks on a
        # full match, so neither a reused inode nor an in-place content swap
        # can be misread as the file this call created.
        self._materialized_by_call: dict[str, _EnvFileIdentity] = {}

    @property
    def name(self) -> str:
        return DRIVER_NAME

    @property
    def provision_on_init(self) -> bool:
        """Whether provisioning runs on ``after_init`` (E10-S1 R3)."""

        return self._config.provision_on_init

    @property
    def provision_on_adopt(self) -> bool:
        """Whether provisioning runs on ``after_adopt`` (E10-S1 R4)."""

        return self._config.provision_on_adopt

    @property
    def remove_volumes_on_destroy(self) -> bool:
        """Whether ``cleanup`` removes volumes with ``down -v`` (E10-S1 R7).

        Exposed so a downstream capability (E10-S3 data ``cleanup_mode='runtime'``)
        can verify the runtime is configured to actually retire the target
        volumes before accepting a delegated cleanup contract.
        """

        return self._config.remove_volumes_on_destroy

    def project_name(self, workspace: RuntimeWorkspace) -> str:
        raw = self._config.project_pattern.replace(
            "{project}", self._project_name
        ).replace("{target}", workspace.target)
        return sanitize_project_name(raw)

    def _resolve_extra_compose_files(self, cwd: str) -> tuple[str, ...]:
        """Resolve which ``compose_files`` entries actually exist (E10-S1 §12).

        Mirrors the legacy harness's optional override: an entry that does not
        exist is silently omitted (never fails provisioning), but a present
        entry MUST resolve inside ``cwd`` (symlink-aware, audit H5.B shares the
        H2/H3 boundary-escape root cause) or provisioning fails closed.
        """

        if not self._config.compose_files:
            return ()
        from ...security import PathBoundaryError, resolve_within_directory

        base = Path(cwd)
        resolved: list[str] = []
        for rel in self._config.compose_files:
            try:
                candidate = resolve_within_directory(base, rel)
            except PathBoundaryError as exc:
                raise CapabilityConfigInvalidError(
                    f"runtime: 'compose_files' entry '{rel}' escapes the "
                    f"boundary: {exc}"
                ) from exc
            if candidate.is_file():
                resolved.append(rel)
        return tuple(resolved)

    def base_project_name(self) -> str:
        """Derive the shared base runtime project identity (E10-S1 R9).

        Project scope uses ``base_project_pattern`` with ``{project}`` only (no
        ``{target}``), so a source/base runtime is distinct from every
        per-target workspace runtime and deterministic across calls.
        """

        raw = self._config.base_project_pattern.replace(
            "{project}", self._project_name
        )
        return sanitize_project_name(raw)

    def _scoped_project(
        self, scope: RuntimeScope, workspace: RuntimeWorkspace | None
    ) -> str:
        """Resolve the Compose project identity for a runtime scope (E10-S1 R9)."""

        if scope is RuntimeScope.PROJECT:
            return self.base_project_name()
        if workspace is None:
            raise ValueError("workspace scope requires a RuntimeWorkspace")
        return self.project_name(workspace)

    def _scoped_cwd(
        self, scope: RuntimeScope, workspace: RuntimeWorkspace | None
    ) -> str:
        """Resolve the working directory for a runtime scope (E10-S1 R2).

        Project scope runs from the repository root; workspace scope from the
        target worktree.  Both keep Compose file resolution deterministic.
        """

        if scope is RuntimeScope.PROJECT:
            if self._repository_root is None:
                raise ValueError("project scope requires a repository root")
            return str(self._repository_root)
        if workspace is None:
            raise ValueError("workspace scope requires a RuntimeWorkspace")
        return str(workspace.worktree_path)

    def _env(self, workspace: RuntimeWorkspace) -> dict[str, str]:
        """Derive explicit, non-secret env for the runtime (R9/R10).

        When a port env var name is configured and a reservation exists, inject
        the reserved port under that project-defined variable name -- no
        SiVale-specific variable is hardcoded.
        """

        env: dict[str, str] = {}
        if self._config.port_env and self._port_provider is not None:
            port = self._port_provider(workspace)
            if port is not None:
                env[self._config.port_env] = str(port)
        return env

    def doctor(
        self, workspace: RuntimeWorkspace | None
    ) -> tuple[RuntimeDoctorCheck, ...]:
        checks = [
            RuntimeDoctorCheck(
                "DOCKER_AVAILABLE",
                self._runner.available,
                "docker available" if self._runner.available else "docker not found",
            ),
            RuntimeDoctorCheck(
                "DOCKER_COMPOSE_AVAILABLE",
                self._runner.compose_available(),
                "docker compose available"
                if self._runner.compose_available()
                else "docker compose not available",
            ),
        ]
        # E6-S2 R2 (audit H6): verify the configured compose file exists.  With
        # a concrete workspace, check it inside the target worktree; without one
        # (project-level ``doctor``), fall back to the repository root so the
        # check still runs in the normal, target-less ``ramalio doctor`` case.
        compose_path: Path | None = None
        if workspace is not None:
            compose_path = self._compose_file_path(workspace)
        elif self._repository_root is not None:
            compose_path = self._repository_root / self._config.compose_file
        if compose_path is not None:
            exists = compose_path.is_file()
            checks.append(
                RuntimeDoctorCheck(
                    "DOCKER_COMPOSE_FILE",
                    exists,
                    f"compose file {self._config.compose_file} present"
                    if exists
                    else f"compose file {compose_path} not found",
                )
            )
        return tuple(checks)

    def _compose_file_path(self, workspace: RuntimeWorkspace) -> Path:
        return workspace.worktree_path / self._config.compose_file

    def start(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        # E7-S0 R3/R11 (audit H2/H4): the driver is authoritative about whether
        # THIS call actually brought the runtime up.  ``docker compose up -d``
        # is idempotent, so observe the running state first.  The observation is
        # tri-state: True (was running), False (demonstrably not running) or
        # None (could not observe -> ``changed`` is left UNKNOWN so the
        # capability applies its fail-closed rollback heuristic and never claims
        # ownership it cannot prove).
        before = self._running_state(workspace)
        result = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            "up",
            "-d",
            cwd=str(workspace.worktree_path),
            env=self._env(workspace),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if result.returncode != 0:
            # Audit H4: ``up`` may have started SOME services before failing
            # (partial mutation).  Surface a structured failure that declares a
            # possible mutation so the caller can journal/compensate it instead
            # of assuming zero mutation on a non-zero exit.
            raise RuntimeStartFailedError(
                f"docker compose up failed: {redact_diagnostic(result.stderr)}",
                changed=self._mutation_after_failed_start(before, workspace),
                resource_identity=self.project_name(workspace),
                compensation_available=True,
            )
        changed = None if before is None else (not before)
        return RuntimeResult(RuntimeState.RUNNING, "compose up -d", changed=changed)

    def provision(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        """Prepare/bring up the per-target runtime during provisioning (E10-S1 R8).

        Steps, in order:

        1. if ``materialize_env_file`` is configured, copy the repository-root
           source into the worktree destination BEFORE any Compose command
           (R8.1/R12); the content is never printed and the copy does not make
           it versioned config;
        2. observe the pre-state with the same fail-closed criterion as
           ``start`` (R8.2);
        3. run ``docker compose ... up -d`` (R8.3), adding ``--build`` only when
           ``build_on_provision=true`` (R8.4);
        4. report ``changed`` with the same ownership semantics as ``start``
           (R8.5).
        """

        if self._config.materialize_env_file is not None:
            self._materialize_env_file(workspace)

        before = self._running_state(workspace)
        args = ["up", "-d"]
        if self._config.build_on_provision:
            args.append("--build")
        result = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            *args,
            cwd=str(workspace.worktree_path),
            env=self._env(workspace),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if result.returncode != 0:
            # Audit H3: if this call materialized the env file, that mutation
            # must be compensable regardless of whether Compose itself left
            # resources behind — otherwise the created file would be orphaned
            # (never retired) on a provision failure.  Compensation itself only
            # ever retires the file THIS call created (never a preexisting
            # one); see compensate_materialize_env_file.
            materialized_this_call = self._materialized_by_call.get(
                workspace.target, False
            )
            compose_mutation = self._mutation_after_failed_start(before, workspace)
            changed = True if materialized_this_call else compose_mutation
            raise RuntimeStartFailedError(
                f"docker compose up failed during provision: "
                f"{redact_diagnostic(result.stderr)}",
                changed=changed,
                resource_identity=self.project_name(workspace),
                compensation_available=True,
            )
        changed = None if before is None else (not before)
        if self._materialized_by_call.get(workspace.target, False):
            # The materialized file is a mutation THIS call owns, independent
            # of whether Compose itself was already running (audit H3): a
            # later capability failure must still be able to compensate it.
            changed = True
        summary = "compose up -d --build" if self._config.build_on_provision else "compose up -d"
        return RuntimeResult(RuntimeState.RUNNING, summary, changed=changed)

    def _materialize_env_file(self, workspace: RuntimeWorkspace) -> None:
        """Copy the configured env file from the repository root into the
        worktree, with a safe, idempotent, ownership-aware semantics (E10-S1
        §4, audit H3):

        * destination resolves outside the worktree (symlink or otherwise)
          -> FAIL, nothing is written (E7-S2 boundary);
        * destination exists and its bytes are identical to the source
          -> no-op (idempotent re-provisioning, e.g. repeated ``init``);
        * destination exists and differs
          -> FAIL, preexisting work is preserved untouched (E10-S4 R2: adopt
          must never silently overwrite a worktree's own ``.env``);
        * destination does not exist
          -> create it and record that THIS call owns it, so a later failure
          in the same operation can retire exactly this file (never a
          preexisting one) via :meth:`compensate_materialize_env_file`.

        The source path is validated the same way relative to the repository
        root.  File content is never printed or logged (R12).
        """

        rel = self._config.materialize_env_file
        assert rel is not None  # guarded by caller
        if self._repository_root is None:
            raise RuntimeStartFailedError(
                "cannot materialize env file: repository root is unknown",
                changed=False,
            )

        from ...security import PathBoundaryError, resolve_within_directory

        try:
            source = resolve_within_directory(self._repository_root, rel)
        except PathBoundaryError as exc:
            raise RuntimeStartFailedError(
                f"materialize_env_file source '{rel}' escapes the repository "
                f"root boundary: {exc}",
                changed=False,
            ) from exc
        if not source.is_file():
            # Fail before start; do not reveal file contents (R12).
            raise RuntimeStartFailedError(
                f"materialize_env_file source '{rel}' does not exist at the "
                "repository root",
                changed=False,
            )

        destination_parent_created = False
        parent_rel = str(PurePosixPath(rel).parent)
        try:
            if parent_rel not in (".", ""):
                workspace.worktree_path.joinpath(parent_rel).mkdir(
                    parents=True, exist_ok=True
                )
            destination = resolve_within_directory(workspace.worktree_path, rel)
        except PathBoundaryError as exc:
            raise RuntimeStartFailedError(
                f"materialize_env_file destination '{rel}' escapes the worktree "
                f"boundary: {exc}",
                changed=False,
            ) from exc

        target = workspace.target
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise RuntimeStartFailedError(
                    f"materialize_env_file destination '{rel}' already exists "
                    "and is not a regular file; refusing to overwrite "
                    "preexisting work",
                    changed=False,
                )
            # Idempotent re-provisioning: identical content is a safe no-op.
            # This call does not own the (preexisting) file, so nothing is
            # tracked for compensation.
            if _files_identical(source, destination):
                self._materialized_by_call.pop(target, None)
                return
            # E10-S4 R2: a preexisting, DIFFERENT .env is the worktree's own
            # work (e.g. adopted). Never silently overwrite it.
            raise RuntimeStartFailedError(
                f"materialize_env_file destination '{rel}' already exists with "
                "different content; refusing to overwrite preexisting work "
                "(preserve it or remove materialize_env_file from config)",
                changed=False,
            )

        # Destination does not exist: this call creates and owns it.
        # shutil.copyfile copies bytes without echoing content anywhere.
        #
        # F1.3 (ownership window + transactional integration): from the instant
        # ``copyfile`` may have created the destination, a failure before
        # ownership is durably recorded would leave a file this call created
        # that the transaction does not know is ours — an orphaned mutation
        # compensation could never retire (E10-S0 ownership/rollback contract,
        # INV-01/INV-03). Two things guarantee this never happens:
        #
        # 1. The identity digest is computed from the SOURCE bytes (already
        #    copied verbatim by ``copyfile``), NOT by reading the destination
        #    back — so seeding the identity no longer depends on a second read
        #    of the just-created file that could fail after the mutation.
        # 2. If capturing/registering the identity still fails, we retire the
        #    file we just created (best-effort, symlink-safe). If that cleanup
        #    ALSO fails, the created .env is still present, so we MUST surface
        #    the mutation to the transaction model: we raise a
        #    ``RuntimeStartFailedError`` (a ``PartialMutationError``) with
        #    ``changed=True`` and ``compensation_available=True`` so
        #    ``HookRunner._record_partial_mutation`` records a transaction step
        #    and rollback drives ``RuntimeCapability.compensate`` ->
        #    ``compensate_materialize_env_file`` to retire it (or classify the
        #    rollback PARTIAL). A bare ``OSError`` would NOT be recognized as a
        #    partial mutation and would be lost, which is the bug this fixes.
        try:
            # Digest of the exact bytes we are about to write, read from the
            # SOURCE (never the destination). Used only in memory for identity
            # comparison; never logged (INV-08).
            source_bytes = source.read_bytes()
        except OSError as exc:  # pragma: no cover - source vanished mid-op
            raise RuntimeStartFailedError(
                f"materialize_env_file source '{rel}' could not be read",
                changed=False,
            ) from exc

        shutil.copyfile(source, destination)
        try:
            # Capture the created file's STRONG identity at creation time, so
            # compensation can verify — before ever unlinking anything — that
            # the lexical path still refers to this exact same file and was not
            # swapped for a symlink, a reused inode, or a different/rewritten
            # regular file in the meantime (F1-followup identity check).
            created_stat = destination.lstat()
            identity = _EnvFileIdentity.from_stat_and_bytes(created_stat, source_bytes)
        except BaseException as capture_exc:
            # Identity could not be witnessed after the file was created. Retire
            # the file we just created (best-effort, symlink-safe). ``os.path``
            # probes are used so cleanup does not depend on ``Path.lstat`` (the
            # very call that may have raised).
            import os

            cleanup_ok = False
            try:
                if os.path.exists(destination) and not os.path.islink(destination) \
                        and os.path.isfile(destination):
                    os.unlink(destination)
                    cleanup_ok = True
                elif not os.path.exists(destination):
                    # Already gone: nothing was left behind.
                    cleanup_ok = True
            except OSError:
                cleanup_ok = False

            if cleanup_ok:
                # The created file was retired; no mutation remains. Report the
                # failure with ``changed=False`` so no compensation step is
                # recorded, but never as success (INV-05).
                raise RuntimeStartFailedError(
                    "materialize_env_file failed to record ownership after "
                    "creating the destination; the created file was retired",
                    changed=False,
                ) from capture_exc

            # Cleanup ALSO failed: the created .env is still present. Record a
            # degraded (unverified) ownership entry so the driver-level
            # compensation still knows a file was created here, AND surface the
            # mutation to the transaction model via PartialMutationError so
            # rollback drives the real compensation (this is the E7/E10 path,
            # not a driver-local workaround).
            self._materialized_by_call[target] = _EnvFileIdentity.unverified()
            raise RuntimeStartFailedError(
                "materialize_env_file created the destination but could not "
                "record its identity or retire it; the mutation must be "
                "compensated by rollback",
                changed=True,
                resource_identity=f"materialize_env_file:{target}",
                compensation_available=True,
            ) from capture_exc
        self._materialized_by_call[target] = identity

    def compensate_materialize_env_file(self, workspace: RuntimeWorkspace) -> None:
        """Retire the env file THIS call created, if any (audit H3/F1, E7-S0 R3).

        Never removes a preexisting file: only a file this operation actually
        created (tracked per target) is compensated.  A no-op when
        ``materialize_env_file`` is not configured or nothing was created.

        F1 fix: a failure to retire the file (boundary re-check or ``unlink``)
        MUST propagate instead of being swallowed. ``LifecycleTransaction``
        already catches compensation exceptions and records them as
        ``rollback_errors`` (E7-S0 R6/R7); silently returning here would let a
        failed compensation be misreported as complete while the owned
        resource is still present. Ownership is only cleared from
        ``_materialized_by_call`` *after* the file is confirmed retired (or
        confirmed already absent), so a failed attempt keeps the resource
        tracked as owned and diagnosable for a subsequent retry.

        F1-followup identity check: ``resolve_within_directory`` resolves
        symlinks (it is a boundary check, not an identity check).  If the
        lexical path this call created was later swapped for a symlink into
        ANOTHER in-worktree file, the resolved destination would point at that
        other file, which then legitimately passes ``is_file() and not
        is_symlink()`` and would be deleted even though it is not the resource
        this call created. To prevent that, this method:

        1. ``lstat()``s the LEXICAL path directly (never following symlinks) —
           a symlink at the lexical path is refused outright, never resolved
           and never unlinked;
        2. compares the lexical file's STRONG identity (device, inode,
           creation/modification timestamps, size, and a content digest)
           against the identity captured at creation time — this defeats both
           an immediately reused inode and a same-inode in-place rewrite,
           neither of which a bare ``(st_dev, st_ino)`` pair could detect;
        3. only unlinks when the full identity matches exactly;
        4. raises (without unlinking anything) when the lexical path is a
           symlink, is missing, or its identity no longer matches — the
           resource is no longer demonstrably the one this call owns, so
           rollback must surface as parcial/unsafe rather than delete an
           unrelated file (E7-S0 R3/R11, INV-01/INV-03).

        F1.3 degraded ownership: an entry marked ``verified=False`` records
        that this call created a file at the lexical path but could not witness
        its strong identity (identity capture + immediate cleanup both failed).
        For such an entry there is no digest to compare, so this method fails
        closed: it retires a regular, non-symlink file at the lexical path
        (best effort) and, if retirement fails, propagates the error so the
        mutation surfaces as an inconsistency instead of being silently lost.
        """

        if self._config.materialize_env_file is None:
            return
        target = workspace.target
        created_identity = self._materialized_by_call.get(target)
        if created_identity is None:
            return

        from ...security import PathBoundaryError, resolve_within_directory

        # Boundary re-check still applies to the configured relative path
        # itself (fail closed if the worktree moved/became unsafe); it is
        # NOT used to decide what gets unlinked (see identity check below).
        resolve_within_directory(workspace.worktree_path, self._config.materialize_env_file)

        # Identity check on the LEXICAL path, never following symlinks: this
        # is the only path ever passed to unlink().
        lexical_path = workspace.worktree_path / self._config.materialize_env_file
        try:
            current_stat = lexical_path.lstat()
        except FileNotFoundError:
            # Already gone: nothing to retire; ownership is cleared because
            # the resource this call created is confirmed absent.
            self._materialized_by_call.pop(target, None)
            return

        if stat_module.S_ISLNK(current_stat.st_mode):
            raise PathBoundaryError(
                f"materialize_env_file destination '{self._config.materialize_env_file}' "
                "was replaced by a symlink before compensation; refusing to "
                "follow or delete it (identity not demonstrable)"
            )
        if not stat_module.S_ISREG(current_stat.st_mode):
            # Not a regular file (dir, fifo, device...): never our created
            # resource; refuse to touch it.
            raise PathBoundaryError(
                f"materialize_env_file destination "
                f"'{self._config.materialize_env_file}' is no longer a regular "
                "file; refusing to delete a resource that is not demonstrably "
                "owned"
            )

        # F1.3 degraded ownership: the file was created by THIS call moments
        # ago and could neither have its strong identity witnessed nor be
        # retired immediately. Because ownership is recorded degraded ONLY in
        # that narrow window (right after this call's own ``copyfile``, before
        # returning), the regular file still at the lexical path is
        # demonstrably the one this call created — nothing else could have
        # taken that path in between. We cannot compare a digest we never
        # captured, so fail closed: retire the regular, non-symlink file at the
        # lexical path, then clear ownership. If retirement fails, propagate so
        # the mutation surfaces as an inconsistency (rollback PARTIAL) rather
        # than being silently forgotten (INV-05/INV-06).
        if not created_identity.verified:
            lexical_path.unlink()
            self._materialized_by_call.pop(target, None)
            return

        # Recompute the STRONG identity from the lexical path. The content
        # digest is read from the on-disk bytes and compared in memory only;
        # it is never logged (INV-08). A reused inode or an in-place rewrite
        # will differ in timestamps/size/digest and be rejected here.
        try:
            current_bytes = lexical_path.read_bytes()
        except OSError as exc:
            raise PathBoundaryError(
                f"materialize_env_file destination "
                f"'{self._config.materialize_env_file}' could not be read to "
                "verify ownership before deletion; refusing to delete a "
                "resource that is not demonstrably owned"
            ) from exc
        current_identity = _EnvFileIdentity.from_stat_and_bytes(
            current_stat, current_bytes
        )
        if current_identity != created_identity:
            raise PathBoundaryError(
                f"materialize_env_file destination "
                f"'{self._config.materialize_env_file}' no longer matches the "
                "file this operation created; refusing to delete a resource "
                "that is not demonstrably owned"
            )

        # Identity confirmed: this is exactly the file this call created.
        lexical_path.unlink()
        # Ownership is cleared only once retirement is confirmed.
        self._materialized_by_call.pop(target, None)

    def stop(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        # 'stop' preserves containers/volumes for deterministic resume (R6).
        # E7-S0 R3/R11 (audit H6): report ``changed`` only when something was
        # actually running before this call, so an idempotent stop over an
        # already-stopped runtime is not recorded as a mutation.  A None
        # observation leaves ``changed`` UNKNOWN (capability fail-closed).
        before = self._running_state(workspace)
        result = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            "stop",
            cwd=str(workspace.worktree_path),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if result.returncode != 0:
            raise RuntimeStopFailedError(
                f"docker compose stop failed: {redact_diagnostic(result.stderr)}"
            )
        return RuntimeResult(RuntimeState.STOPPED, "compose stop", changed=before)

    def _mutation_after_failed_start(
        self, before: bool | None, workspace: RuntimeWorkspace
    ) -> bool | None:
        """Whether a failed ``up`` likely left resources behind (audit H4/H1).

        Only claims a *confirmed* mutation (True) when we can prove BOTH that
        nothing was running before (``before is False``) AND that resources now
        exist.  If the pre-state could not be observed (``before is None``), the
        verdict stays None (UNKNOWN): we must not turn "could not observe" into
        "this start created it", because a later rollback would then stop a
        possibly-preexisting runtime (E7-S0 R11).  A None verdict makes the
        transaction record an unsafe, non-compensable step (ROLLBACK_NOT_SAFE).
        """

        if before is None:
            # Pre-state unknown: ownership of any observed resource is unknown.
            return None
        after = self._has_resources(workspace)
        if after is None:
            return None
        if after and not before:
            return True
        # Was already running, or now has none: no *new* mutation attributable
        # to this failed start beyond what preexisted.
        return False

    def _running_state(self, workspace: RuntimeWorkspace) -> bool | None:
        """Tri-state observation of whether any container is running (audit H2).

        Returns True when at least one container is running, False when the
        project is demonstrably not running, and None when the state could not
        be observed (e.g. ``docker compose ps`` failed).  A None result must
        never be collapsed into False, because "could not observe" is not
        "demonstrably stopped" (E7-S0 R3/R11).
        """

        probe = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            "ps",
            "--status=running",
            "--quiet",
            cwd=str(workspace.worktree_path),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if probe.returncode != 0:
            return None
        return bool(probe.stdout.strip())

    def _has_resources(self, workspace: RuntimeWorkspace) -> bool | None:
        """Tri-state observation of whether the Compose project has ANY resource
        that ``down`` would retire (audit H3).

        ``down`` removes stopped containers and networks too, not only running
        containers, so ``cleanup`` must observe *all* project containers via
        ``ps --all`` rather than only the running ones.  Returns None when the
        state could not be observed.
        """

        probe = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            "ps",
            "--all",
            "--quiet",
            cwd=str(workspace.worktree_path),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if probe.returncode != 0:
            return None
        return bool(probe.stdout.strip())

    def status(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        """Map the Compose project to the runtime state vocabulary (E6-S2 R8).

        Uses ``docker compose ps --all --format json`` so per-service state is
        available and maps to the full vocabulary (audit H7):

        * no services at all                       -> STOPPED
        * every service running/healthy            -> RUNNING
        * a mix of running and stopped services    -> DEGRADED
        * any service exited non-zero / unhealthy  -> DEGRADED (or FAILED when
          nothing is running)
        * probe could not run / output unparsable  -> UNKNOWN
        """

        result = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            "ps",
            "--all",
            "--format",
            "json",
            cwd=str(workspace.worktree_path),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if result.returncode != 0:
            return RuntimeResult(RuntimeState.UNKNOWN, "compose ps failed")
        return self._classify_status(result.stdout)

    @staticmethod
    def _classify_status(raw_stdout: str) -> RuntimeResult:
        """Classify ``docker compose ps --format json`` output into a state.

        ``docker compose ps --format json`` emits either a JSON array or one
        JSON object per line depending on the version, so both shapes are
        parsed.  A parse failure yields UNKNOWN rather than a misleading state.
        """

        import json

        text = raw_stdout.strip()
        if not text:
            return RuntimeResult(RuntimeState.STOPPED, "no services")

        services: list[dict] = []
        try:
            parsed = json.loads(text)
            services = parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            # NDJSON: one object per line.
            services = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    services.append(json.loads(line))
                except json.JSONDecodeError:
                    return RuntimeResult(
                        RuntimeState.UNKNOWN, "compose ps output unparsable"
                    )

        if not services:
            return RuntimeResult(RuntimeState.STOPPED, "no services")

        running = 0
        stopped = 0
        failed = 0
        for svc in services:
            state = str(svc.get("State", "")).lower()
            exit_code = svc.get("ExitCode", 0)
            health = str(svc.get("Health", "")).lower()
            if state == "running":
                if health and health not in ("healthy", ""):
                    failed += 1  # running but unhealthy -> degraded contributor
                else:
                    running += 1
            elif state in ("exited", "dead") and exit_code not in (0, None):
                failed += 1
            else:
                stopped += 1

        total = len(services)
        if failed and running == 0:
            return RuntimeResult(RuntimeState.FAILED, "all services failed/stopped")
        if failed:
            return RuntimeResult(RuntimeState.DEGRADED, "some services failed")
        if running == total:
            return RuntimeResult(RuntimeState.RUNNING, "running")
        if running == 0:
            return RuntimeResult(RuntimeState.STOPPED, "stopped")
        return RuntimeResult(RuntimeState.DEGRADED, "partially running")

    def cleanup(self, workspace: RuntimeWorkspace) -> RuntimeResult:
        # Conservative cleanup: remove containers/networks but NOT volumes by
        # default (R7/AC-09). Always identity-scoped with -p (R11).
        # E10-S1 R7: add ``-v`` (remove volumes) ONLY when the project opted in
        # via ``remove_volumes_on_destroy=true``; otherwise keep ``down`` without
        # volumes so data survives a normal destroy.
        # E7-S0 R2/R3 (audit H3): ``down`` retires stopped containers and
        # networks too, so report ``changed`` based on whether the project had
        # ANY resource (``ps --all``), not merely running containers.  A None
        # observation leaves ``changed`` UNKNOWN (capability fail-closed).
        had_resources = self._has_resources(workspace)
        remove_volumes = self._config.remove_volumes_on_destroy
        down_args = ("down", "-v") if remove_volumes else ("down",)
        result = self._runner.compose(
            self.project_name(workspace),
            self._config.compose_file,
            *down_args,
            cwd=str(workspace.worktree_path),
            extra_files=self._resolve_extra_compose_files(str(workspace.worktree_path)),
        )
        if result.returncode != 0:
            raise RuntimeCleanupFailedError(
                f"docker compose down failed: {redact_diagnostic(result.stderr)}"
            )
        summary = (
            "compose down -v (volumes removed)"
            if remove_volumes
            else "compose down (volumes kept)"
        )
        return RuntimeResult(RuntimeState.STOPPED, summary, changed=had_resources)

    # --- RuntimeCommandExecutor (E10-S1 R2/R10/R11) -----------------------

    def ensure_service(
        self,
        scope: RuntimeScope,
        workspace: RuntimeWorkspace | None,
        service: str,
    ) -> RuntimeResult:
        """Bring ``service`` up in the requested scope (E10-S1 R10).

        Runs ``docker compose up -d <service>`` with an explicit project
        identity for the scope (project vs. workspace).  Idempotent: Compose
        leaves an already-running service untouched.
        """

        if not service or not service.strip():
            raise ValueError("ensure_service requires a non-empty service name")
        project = self._scoped_project(scope, workspace)
        cwd = self._scoped_cwd(scope, workspace)
        env = self._env(workspace) if workspace is not None else {}
        result = self._runner.compose(
            project,
            self._config.compose_file,
            "up",
            "-d",
            service,
            cwd=cwd,
            env=env,
            extra_files=self._resolve_extra_compose_files(cwd),
        )
        if result.returncode != 0:
            raise RuntimeStartFailedError(
                f"docker compose up {service} failed: "
                f"{redact_diagnostic(result.stderr)}",
                changed=None,
                resource_identity=project,
                compensation_available=False,
            )
        return RuntimeResult(RuntimeState.RUNNING, f"compose up -d {service}")

    def exec(
        self,
        scope: RuntimeScope,
        workspace: RuntimeWorkspace | None,
        request: RuntimeExecRequest,
    ) -> RuntimeExecResult:
        """Run ``request.argv`` inside a runtime service (E10-S1 R11).

        Builds ``docker compose ... exec -T [--user U] [--workdir W]
        [-e K=V ...] <service> <argv...>``, adding optional flags only when
        present.  Host execution always goes through :class:`SafeProcessRunner`
        with ``shell=False``; nothing is shell-tokenized and stdout/stderr are
        returned as raw bytes without being printed.
        """

        project = self._scoped_project(scope, workspace)
        cwd = self._scoped_cwd(scope, workspace)

        exec_args: list[str] = ["exec", "-T"]
        if request.user is not None:
            exec_args += ["--user", request.user]
        if request.workdir is not None:
            exec_args += ["--workdir", request.workdir]
        for key, value in request.env.items():
            exec_args += ["-e", f"{key}={value}"]
        exec_args.append(request.service)
        exec_args.extend(request.argv)

        completed = self._runner.compose_bytes(
            project,
            self._config.compose_file,
            *exec_args,
            cwd=cwd,
            stdin=request.stdin,
            extra_files=self._resolve_extra_compose_files(cwd),
        )
        return RuntimeExecResult(
            returncode=completed.returncode,
            stdout=completed.stdout or b"",
            stderr=completed.stderr or b"",
        )


def make_driver(
    options: Mapping[str, object], context: "object | None" = None
) -> DockerComposeDriver:
    """Factory used by the runtime driver registry (E6-S0 register_driver).

    ``context`` (a ``DriverBuildContext`` from the runtime capability) carries
    the real project name and a per-target port provider so the driver derives a
    unique ``{project}-{target}`` Compose project (R3/AC-02) and can inject the
    E6-S1 reserved port into the runtime environment (R9/AC-08).  It is optional
    so the driver stays usable standalone in unit tests.
    """

    project_name = "ramalio"
    port_provider = None
    repository_root = None
    if context is not None:
        project_name = getattr(context, "project_name", None) or "ramalio"
        port_provider = getattr(context, "port_provider", None)
        repository_root = getattr(context, "repository_root", None)
    return DockerComposeDriver(
        options,
        project_name=project_name,
        port_provider=port_provider,
        repository_root=repository_root,
    )
