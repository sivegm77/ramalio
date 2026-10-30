"""Doctor service: read-only project/environment diagnostics (E3-S3).

``DoctorService`` runs a battery of small, independent, read-only checks over
the components implemented so far (environment, Git, project, configuration,
target/naming, worktrees) and aggregates them into a global verdict.  It never
repairs, installs, mutates or contacts a remote (INV-01/R21) and never assumes a
specific stack (INV-05).

Checks are registered rather than hardcoded into one monolith (R20, T10): each
check is a small callable receiving a shared :class:`DoctorContext` (which
caches expensive observations) and returning a :class:`DoctorCheckResult`.
Dependent checks return ``SKIP`` when a precondition is missing (7.3), so a
missing Git executable does not abort syntactic project checks it does not need.

The service never prints; it returns a :class:`DoctorReport` the CLI renders.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..config.loader import load_project_config, resolve_project_config
from ..config.models import ResolvedProjectConfig
from ..config.target import build_target_normalizer, build_workspace_naming
from ..core.errors import RamalioError, NotInGitRepositoryError, OperationError
from ..core.project import PROJECT_CONFIG_FILENAME, Project, discover_repository_root
from ..git.repository import GitRepository
from .list_workspaces import ListWorkspacesService, WorkspaceState
from .result import ExitCode


class CheckStatus(Enum):
    """Per-check status (R2)."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class DoctorSection(Enum):
    """Stable output categories, rendered in this order (R18)."""

    ENVIRONMENT = "Environment"
    PROJECT = "Project"
    CONFIGURATION = "Configuration"
    GIT = "Git"
    WORKTREES = "Worktrees"
    EXTENSIONS = "Extensions"


@dataclass(frozen=True, slots=True)
class DoctorCheckResult:
    """Structured result of a single check (R2, INV-03)."""

    check_id: str
    section: DoctorSection
    status: CheckStatus
    summary: str
    details: str | None = None
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleReadiness:
    """Derived (never persisted) lifecycle readiness summary (R17)."""

    ready_for_init: bool
    ready_for_existing_workspace_operations: bool


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Aggregated diagnostic report (R3)."""

    results: tuple[DoctorCheckResult, ...]
    readiness: LifecycleReadiness

    @property
    def global_status(self) -> CheckStatus:
        """Aggregate the global verdict (R3).

        Any FAIL -> FAIL; else any WARN -> WARN; otherwise PASS (SKIP is
        neutral).
        """

        statuses = {r.status for r in self.results}
        if CheckStatus.FAIL in statuses:
            return CheckStatus.FAIL
        if CheckStatus.WARN in statuses:
            return CheckStatus.WARN
        return CheckStatus.PASS

    @property
    def exit_code(self) -> ExitCode:
        """Map the global verdict to an exit code (R4).

        PASS/WARN -> OK; FAIL -> OPERATION_FAILED.  Warnings inform but never
        block on their own.
        """

        if self.global_status is CheckStatus.FAIL:
            return ExitCode.OPERATION_FAILED
        return ExitCode.OK

    def render_lines(self) -> str:
        """Render a section-ordered, human-readable diagnostic (R18)."""

        lines: list[str] = []
        for section in DoctorSection:
            section_results = [r for r in self.results if r.section is section]
            if not section_results:
                continue
            lines.append(f"[{section.value}]")
            for r in section_results:
                line = f"  {r.status.value:<4} {r.check_id}: {r.summary}"
                lines.append(line)
                if r.remediation and r.status in (CheckStatus.FAIL, CheckStatus.WARN):
                    lines.append(f"       -> {r.remediation}")
        lines.append("")
        lines.append(f"Global: {self.global_status.value}")
        lines.append(
            "ready_for_init: "
            f"{'true' if self.readiness.ready_for_init else 'false'}"
        )
        lines.append(
            "ready_for_existing_workspace_operations: "
            + (
                "true"
                if self.readiness.ready_for_existing_workspace_operations
                else "false"
            )
        )
        return "\n".join(lines)


class DoctorContext:
    """Shared, lazily-populated context for checks (7.2).

    Caches the git executable, repository root, raw project TOML and resolved
    configuration so dependent checks avoid redundant work.  Every accessor is
    read-only; discovery/parse failures are captured, not raised, so checks can
    turn them into structured results.
    """

    def __init__(self, start: Path | str | None = None) -> None:
        self._start = start
        self._git_path: str | None = None
        self._git_checked = False

        self._root: Path | None = None
        self._root_error: RamalioError | None = None
        self._root_checked = False

        self._config: ResolvedProjectConfig | None = None
        self._config_error: RamalioError | None = None
        self._config_checked = False

    @property
    def git_available(self) -> bool:
        if not self._git_checked:
            self._git_path = shutil.which("git")
            self._git_checked = True
        return self._git_path is not None

    def repository_root(self) -> tuple[Path | None, RamalioError | None]:
        if not self._root_checked:
            self._root_checked = True
            try:
                self._root = discover_repository_root(self._start)
            except RamalioError as exc:
                self._root_error = exc
        return self._root, self._root_error

    def config(self) -> tuple[ResolvedProjectConfig | None, RamalioError | None]:
        if not self._config_checked:
            self._config_checked = True
            try:
                self._config = resolve_project_config(self._start)
            except RamalioError as exc:
                self._config_error = exc
        return self._config, self._config_error


# A check is a callable from context to a result (7.1); no inheritance required.
DoctorCheck = Callable[[DoctorContext], DoctorCheckResult]


def _result(
    check_id: str,
    section: DoctorSection,
    status: CheckStatus,
    summary: str,
    *,
    details: str | None = None,
    remediation: str | None = None,
) -> DoctorCheckResult:
    return DoctorCheckResult(
        check_id=check_id,
        section=section,
        status=status,
        summary=summary,
        details=details,
        remediation=remediation,
    )


# --- individual checks ----------------------------------------------------


def _check_cli_version(ctx: DoctorContext) -> DoctorCheckResult:
    from .. import __version__

    return _result(
        "CLI_VERSION", DoctorSection.ENVIRONMENT, CheckStatus.PASS,
        f"ramalio {__version__}",
    )


def _check_config_schema(ctx: DoctorContext) -> DoctorCheckResult:
    from .. import SUPPORTED_CONFIG_SCHEMA

    config, _ = ctx.config()
    if config is None:
        return _result(
            "CONFIG_SCHEMA", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    declared = config.meta.schema_version
    return _result(
        "CONFIG_SCHEMA", DoctorSection.CONFIGURATION, CheckStatus.PASS,
        f"config schema v{declared} compatible (CLI supports "
        f"v{SUPPORTED_CONFIG_SCHEMA})",
    )


def _check_git_available(ctx: DoctorContext) -> DoctorCheckResult:
    if ctx.git_available:
        return _result(
            "GIT_AVAILABLE", DoctorSection.ENVIRONMENT, CheckStatus.PASS,
            "git executable found on PATH",
        )
    return _result(
        "GIT_AVAILABLE", DoctorSection.ENVIRONMENT, CheckStatus.FAIL,
        "git executable not found on PATH",
        remediation="Install Git and ensure it is on PATH.",
    )


def _check_git_repository(ctx: DoctorContext) -> DoctorCheckResult:
    if not ctx.git_available:
        return _result(
            "GIT_REPOSITORY", DoctorSection.GIT, CheckStatus.SKIP,
            "skipped: git is not available",
        )
    root, error = ctx.repository_root()
    if root is not None:
        return _result(
            "GIT_REPOSITORY", DoctorSection.GIT, CheckStatus.PASS,
            f"inside a Git repository ({root})",
        )
    return _result(
        "GIT_REPOSITORY", DoctorSection.GIT, CheckStatus.FAIL,
        "current directory is not inside a Git repository",
        details=str(error) if error else None,
        remediation="Run ramalio from within a Git repository.",
    )


def _check_main_checkout(ctx: DoctorContext) -> DoctorCheckResult:
    if not ctx.git_available:
        return _result(
            "GIT_MAIN_CHECKOUT", DoctorSection.GIT, CheckStatus.SKIP,
            "skipped: git is not available",
        )
    root, _ = ctx.repository_root()
    if root is None:
        return _result(
            "GIT_MAIN_CHECKOUT", DoctorSection.GIT, CheckStatus.SKIP,
            "skipped: no repository",
        )
    try:
        repo = GitRepository.from_root(root)
        repo.ensure_valid()
    except RamalioError as exc:
        return _result(
            "GIT_MAIN_CHECKOUT", DoctorSection.GIT, CheckStatus.FAIL,
            "main checkout is not a coherent working tree",
            details=str(exc),
        )
    return _result(
        "GIT_MAIN_CHECKOUT", DoctorSection.GIT, CheckStatus.PASS,
        "main checkout is a coherent working tree",
    )


def _check_config_present(ctx: DoctorContext) -> DoctorCheckResult:
    root, _ = ctx.repository_root()
    if root is None:
        return _result(
            "CONFIG_PRESENT", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: no repository root",
        )
    config_path = root / PROJECT_CONFIG_FILENAME
    if config_path.is_file():
        return _result(
            "CONFIG_PRESENT", DoctorSection.CONFIGURATION, CheckStatus.PASS,
            f"{PROJECT_CONFIG_FILENAME} found",
        )
    return _result(
        "CONFIG_PRESENT", DoctorSection.CONFIGURATION, CheckStatus.FAIL,
        f"{PROJECT_CONFIG_FILENAME} not found at repository root",
        remediation=f"Create {PROJECT_CONFIG_FILENAME} at the repository root.",
    )


def _check_config_valid(ctx: DoctorContext) -> DoctorCheckResult:
    root, _ = ctx.repository_root()
    if root is None:
        return _result(
            "CONFIG_VALID", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: no repository root",
        )
    if not (root / PROJECT_CONFIG_FILENAME).is_file():
        return _result(
            "CONFIG_VALID", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: configuration file missing",
        )
    _, error = ctx.config()
    if error is None:
        return _result(
            "CONFIG_VALID", DoctorSection.CONFIGURATION, CheckStatus.PASS,
            "configuration parses and validates",
        )
    return _result(
        "CONFIG_VALID", DoctorSection.CONFIGURATION, CheckStatus.FAIL,
        "configuration is invalid",
        details=str(error),
        remediation="Fix the reported configuration error.",
    )


def _check_base_branch(ctx: DoctorContext) -> DoctorCheckResult:
    config, error = ctx.config()
    if config is None:
        return _result(
            "BASE_BRANCH", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    if not ctx.git_available:
        return _result(
            "BASE_BRANCH", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: git is not available",
        )
    root, _ = ctx.repository_root()
    if root is None:
        return _result(
            "BASE_BRANCH", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: no repository root",
        )
    repo = GitRepository.from_root(root)
    name = config.project.base_branch
    if repo.branch_exists(name):
        return _result(
            "BASE_BRANCH", DoctorSection.CONFIGURATION, CheckStatus.PASS,
            f"base branch '{name}' exists locally",
        )
    return _result(
        "BASE_BRANCH", DoctorSection.CONFIGURATION, CheckStatus.FAIL,
        f"base branch '{name}' does not exist locally",
        remediation=(
            "Ensure the configured base branch exists locally "
            "(ramalio does not fetch)."
        ),
    )


def _check_target_policy(ctx: DoctorContext) -> DoctorCheckResult:
    config, _ = ctx.config()
    if config is None:
        return _result(
            "TARGET_POLICY", DoctorSection.PROJECT, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    try:
        # Building the normalizer compiles the regex and validates the example.
        build_target_normalizer(config)
    except RamalioError as exc:
        return _result(
            "TARGET_POLICY", DoctorSection.PROJECT, CheckStatus.FAIL,
            "target policy is invalid",
            details=str(exc),
            remediation="Fix target.regex / target.example / case policy.",
        )
    return _result(
        "TARGET_POLICY", DoctorSection.PROJECT, CheckStatus.PASS,
        "target regex, example and case policy are valid",
    )


def _check_normalization(ctx: DoctorContext) -> DoctorCheckResult:
    config, _ = ctx.config()
    if config is None:
        return _result(
            "NORMALIZATION", DoctorSection.PROJECT, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    example = config.target.example
    if not example:
        return _result(
            "NORMALIZATION", DoctorSection.PROJECT, CheckStatus.SKIP,
            "skipped: no example configured",
        )
    try:
        normalizer = build_target_normalizer(config)
        result = normalizer.normalize(example)
    except RamalioError as exc:
        return _result(
            "NORMALIZATION", DoctorSection.PROJECT, CheckStatus.FAIL,
            "normalization of the example does not yield a valid target",
            details=str(exc),
        )
    return _result(
        "NORMALIZATION", DoctorSection.PROJECT, CheckStatus.PASS,
        f"example normalizes to a valid target ('{result.target.value}')",
    )


def _check_branch_pattern(ctx: DoctorContext) -> DoctorCheckResult:
    config, _ = ctx.config()
    if config is None:
        return _result(
            "BRANCH_PATTERN", DoctorSection.PROJECT, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    try:
        normalizer = build_target_normalizer(config)
        target = normalizer.normalize(config.target.example).target
        naming = build_workspace_naming(config)
        branch = naming.derive_branch(target)
    except RamalioError as exc:
        return _result(
            "BRANCH_PATTERN", DoctorSection.PROJECT, CheckStatus.FAIL,
            "branch pattern does not produce a valid Git ref",
            details=str(exc),
            remediation="Fix branch.pattern.",
        )
    return _result(
        "BRANCH_PATTERN", DoctorSection.PROJECT, CheckStatus.PASS,
        f"branch pattern yields a valid ref ('{branch}')",
    )


def _check_worktree_pattern(ctx: DoctorContext) -> DoctorCheckResult:
    config, _ = ctx.config()
    if config is None:
        return _result(
            "WORKTREE_PATTERN", DoctorSection.PROJECT, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    try:
        normalizer = build_target_normalizer(config)
        target = normalizer.normalize(config.target.example).target
        naming = build_workspace_naming(config)
        path = naming.derive_worktree_path(target)
    except RamalioError as exc:
        return _result(
            "WORKTREE_PATTERN", DoctorSection.PROJECT, CheckStatus.FAIL,
            "worktree pattern does not produce a safe path",
            details=str(exc),
            remediation="Fix worktree.directory / worktree.pattern.",
        )
    return _result(
        "WORKTREE_PATTERN", DoctorSection.PROJECT, CheckStatus.PASS,
        f"worktree pattern yields a safe relative path ('{path}')",
    )


def _check_worktree_directory_boundary(ctx: DoctorContext) -> DoctorCheckResult:
    config, _ = ctx.config()
    if config is None:
        return _result(
            "WORKTREE_DIRECTORY", DoctorSection.CONFIGURATION, CheckStatus.SKIP,
            "skipped: configuration unavailable",
        )
    directory = config.worktree.directory
    # Read-only boundary evaluation only; never create/touch anything (R16/R21).
    if directory.startswith("/") or ".." in Path(directory).parts:
        return _result(
            "WORKTREE_DIRECTORY", DoctorSection.CONFIGURATION, CheckStatus.FAIL,
            f"worktree.directory '{directory}' is not a safe relative path",
            remediation="Use a relative directory inside the repository.",
        )
    root, _ = ctx.repository_root()
    if root is not None and not (root / directory).exists():
        # A not-yet-existing worktree directory is normal for a freshly
        # configured project; init will create it (R16).  Report PASS with a
        # note rather than degrading the healthy-project verdict (AC-01).
        return _result(
            "WORKTREE_DIRECTORY", DoctorSection.CONFIGURATION, CheckStatus.PASS,
            f"worktree directory '{directory}' is a safe relative path "
            "(will be created on init)",
        )
    return _result(
        "WORKTREE_DIRECTORY", DoctorSection.CONFIGURATION, CheckStatus.PASS,
        f"worktree directory '{directory}' is a safe relative path",
    )


def _check_current_worktrees(ctx: DoctorContext) -> DoctorCheckResult:
    config, _ = ctx.config()
    if config is None or not ctx.git_available:
        return _result(
            "WORKTREES", DoctorSection.WORKTREES, CheckStatus.SKIP,
            "skipped: configuration or git unavailable",
        )
    root, _ = ctx.repository_root()
    if root is None:
        return _result(
            "WORKTREES", DoctorSection.WORKTREES, CheckStatus.SKIP,
            "skipped: no repository root",
        )
    try:
        listing = ListWorkspacesService(
            config, repository=GitRepository.from_root(root)
        ).run()
    except RamalioError as exc:
        return _result(
            "WORKTREES", DoctorSection.WORKTREES, CheckStatus.WARN,
            "could not fully inspect worktrees",
            details=str(exc),
        )

    anomalous_states = {
        WorkspaceState.INCONSISTENT,
        WorkspaceState.PRUNABLE,
        WorkspaceState.DETACHED,
        WorkspaceState.UNRECOGNIZED,
    }
    anomalies = [i for i in listing.items if i.state in anomalous_states]
    if not anomalies:
        recognized = sum(1 for i in listing.items if i.recognized)
        return _result(
            "WORKTREES", DoctorSection.WORKTREES, CheckStatus.PASS,
            f"{recognized} managed workspace(s), no anomalies",
        )
    detail = ", ".join(
        f"{i.state.value} @ {i.path}" for i in anomalies
    )
    return _result(
        "WORKTREES", DoctorSection.WORKTREES, CheckStatus.WARN,
        f"{len(anomalies)} worktree anomaly/anomalies detected",
        details=detail,
        remediation="Inspect the reported worktrees; doctor never repairs them.",
    )


def _check_locks(ctx: DoctorContext) -> DoctorCheckResult:
    """Report active/stale lifecycle locks read-only (E7-S1 R10/R16).

    Never acquires or removes a lock.  Classification is based on whether the OS
    lock is *actually held right now* (a non-blocking ``flock`` probe), not on
    whether a lock *file* merely exists or whose recorded PID happens to be
    alive: a lock file persists on disk after its holder releases it, so a
    released-but-leftover file must never be reported as an active or stale
    lock (R10/R16).  A lock that IS held but whose recorded owner PID no longer
    exists is the genuine *stale* case reported as WARN; ``doctor`` never
    recovers it automatically (R11).
    """

    root, _ = ctx.repository_root()
    if root is None:
        return _result(
            "LOCKS", DoctorSection.WORKTREES, CheckStatus.SKIP,
            "skipped: no repository root",
        )
    from ..resources.locks import LockManager

    manager = LockManager.for_repository(root)
    classified = manager.classify_locks()
    # Only locks actually held right now are relevant; leftover lock files whose
    # flock is free are neither active nor stale (R10).
    held = [info for info, is_held in classified if is_held]
    if not held:
        return _result(
            "LOCKS", DoctorSection.WORKTREES, CheckStatus.PASS,
            "no lifecycle locks held",
        )
    stale = [info for info in held if not manager.is_pid_alive(info.pid)]
    active = [info for info in held if manager.is_pid_alive(info.pid)]
    if stale:
        detail = ", ".join(
            f"{info.scope}:{info.key} (pid {info.pid}, op '{info.operation}')"
            for info in stale
        )
        return _result(
            "LOCKS", DoctorSection.WORKTREES, CheckStatus.WARN,
            f"{len(stale)} stale lock(s), {len(active)} active",
            details=detail,
            remediation=(
                "A stale lock is released automatically when its process dies; "
                "doctor never removes locks by age."
            ),
        )
    return _result(
        "LOCKS", DoctorSection.WORKTREES, CheckStatus.PASS,
        f"{len(active)} active lifecycle lock(s), none stale",
    )


# Default, ordered check registry.  New checks (including E4 capability checks)
# register here without changing the aggregation semantics (R20, T10).
_DEFAULT_CHECKS: tuple[DoctorCheck, ...] = (
    _check_cli_version,
    _check_git_available,
    _check_git_repository,
    _check_main_checkout,
    _check_config_present,
    _check_config_valid,
    _check_config_schema,
    _check_base_branch,
    _check_target_policy,
    _check_normalization,
    _check_branch_pattern,
    _check_worktree_pattern,
    _check_worktree_directory_boundary,
    _check_current_worktrees,
    _check_locks,
)


class DoctorService:
    """Run the registered diagnostic checks and aggregate them (7.1, T1/T2)."""

    def __init__(
        self,
        *,
        start: Path | str | None = None,
        checks: Iterable[DoctorCheck] | None = None,
        registry: "object | None" = None,
        integration_registry: "object | None" = None,
    ) -> None:
        self._start = start
        self._checks = tuple(checks) if checks is not None else _DEFAULT_CHECKS
        # E4-S0: capabilities contribute doctor checks through the registry
        # without the doctor core knowing any concrete capability (R11/INV-06).
        if registry is None:
            from ..capabilities import default_registry

            registry = default_registry()
        self._registry = registry
        self._integration_registry = integration_registry

    @classmethod
    def from_directory(cls, start: Path | str | None = None) -> "DoctorService":
        return cls(start=start)

    def register(self, check: DoctorCheck) -> None:
        """Register an additional check (extension seam for E4, R20)."""

        self._checks = self._checks + (check,)

    def run(self) -> DoctorReport:
        """Execute all checks and build the aggregated report (7.1)."""

        ctx = DoctorContext(self._start)
        results = list(check(ctx) for check in self._checks)
        results.extend(self._capability_results(ctx))
        results.extend(self._integration_results(ctx))
        results_tuple = tuple(results)
        readiness = self._derive_readiness(results_tuple)
        return DoctorReport(results=results_tuple, readiness=readiness)

    def _capability_results(
        self, ctx: DoctorContext
    ) -> tuple[DoctorCheckResult, ...]:
        """Adapt capability-contributed checks into doctor results (R11, 7.4).

        Runs only when configuration is available (capabilities are configured
        per project).  The doctor core never references a concrete capability;
        it just forwards whatever the registry collected, mapping the
        capability check status to the doctor status.  The registry's error
        boundary already converts a misbehaving capability into a FAIL check.
        """

        config, _ = ctx.config()
        if config is None:
            return ()
        from ..capabilities import CapabilityContext
        from ..capabilities.base import DoctorCheckStatus as CapCheckStatus

        cap_ctx = CapabilityContext(config=config)
        # First surface unknown/invalid capability configuration as a FAIL (R13).
        try:
            self._registry.verify_configuration(cap_ctx)
        except RamalioError as exc:
            return (
                _result(
                    "CAPABILITIES", DoctorSection.EXTENSIONS, CheckStatus.FAIL,
                    "capability configuration is invalid",
                    details=str(exc),
                    remediation="Fix the capabilities section in the config.",
                ),
            )

        try:
            contributed = self._registry.collect_doctor_checks(cap_ctx)
        except RamalioError as exc:
            return (
                _result(
                    "CAPABILITIES", DoctorSection.EXTENSIONS, CheckStatus.FAIL,
                    "capability configuration is invalid",
                    details=str(exc),
                ),
            )

        mapping = {
            CapCheckStatus.PASS: CheckStatus.PASS,
            CapCheckStatus.WARN: CheckStatus.WARN,
            CapCheckStatus.FAIL: CheckStatus.FAIL,
            CapCheckStatus.SKIP: CheckStatus.SKIP,
        }
        return tuple(
            _result(
                c.check_id,
                DoctorSection.EXTENSIONS,
                mapping[c.status],
                c.summary,
                details=c.details,
                remediation=c.remediation,
            )
            for c in contributed
        )

    def _integration_results(
        self, ctx: DoctorContext
    ) -> tuple[DoctorCheckResult, ...]:
        """Contribute availability checks for enabled integrations (E5-S2 R7/R8).

        An enabled integration whose command is unavailable is a FAIL; a disabled
        integration does not participate (R8).  Uses the default integration
        registry unless one was injected.
        """

        config, _ = ctx.config()
        if config is None:
            return ()
        registry = self._integration_registry
        if registry is None:
            from ..integrations import default_integration_registry

            registry = default_integration_registry()

        from ..integrations import IntegrationContext

        results: list[DoctorCheckResult] = []
        for integration in registry.all():
            entry = config.integrations.get(integration.name)
            if entry is None or not entry.enabled:
                continue  # R8: disabled integrations do not participate.
            # Doctor-level context has no specific target; use the repo root as
            # a placeholder worktree only for availability evaluation.
            int_ctx = IntegrationContext(
                config=config,
                target="",
                worktree_path=config.repository_root,
            )
            try:
                integration.validate_config(int_ctx)
                available = integration.is_available(int_ctx)
            except RamalioError as exc:
                results.append(
                    _result(
                        f"INTEGRATION_{integration.name.upper()}",
                        DoctorSection.EXTENSIONS,
                        CheckStatus.FAIL,
                        f"integration '{integration.name}' configuration invalid",
                        details=str(exc),
                    )
                )
                continue
            results.append(
                _result(
                    f"INTEGRATION_{integration.name.upper()}",
                    DoctorSection.EXTENSIONS,
                    CheckStatus.PASS if available else CheckStatus.FAIL,
                    (
                        f"integration '{integration.name}' available"
                        if available
                        else f"integration '{integration.name}' command not available"
                    ),
                    remediation=None
                    if available
                    else f"Install the '{integration.name}' tool or fix its command.",
                )
            )
        return tuple(results)

    def _derive_readiness(
        self, results: tuple[DoctorCheckResult, ...]
    ) -> LifecycleReadiness:
        """Derive lifecycle readiness from check results (R17).

        Readiness is never persisted; it is a pure function of the checks.  A
        FAIL in any check blocks readiness; the two flags currently share the
        same core prerequisites (Git + repository + valid configuration).
        """

        by_id = {r.check_id: r for r in results}

        def ok(check_id: str) -> bool:
            r = by_id.get(check_id)
            return r is not None and r.status is CheckStatus.PASS

        core_ready = (
            ok("GIT_AVAILABLE")
            and ok("GIT_REPOSITORY")
            and ok("CONFIG_PRESENT")
            and ok("CONFIG_VALID")
            and ok("BASE_BRANCH")
            and ok("TARGET_POLICY")
            and ok("BRANCH_PATTERN")
            and ok("WORKTREE_PATTERN")
        )
        return LifecycleReadiness(
            ready_for_init=core_ready,
            ready_for_existing_workspace_operations=core_ready,
        )
