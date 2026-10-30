"""Expected error hierarchy for ramalio."""

from __future__ import annotations

from .result import ExitCode


class RamalioError(Exception):
    """Base class for expected, user-facing product errors."""

    exit_code: ExitCode = ExitCode.OPERATION_FAILED

    def __init__(self, message: str) -> None:
        message = str(message).strip()
        if not message:
            message = self.__class__.__name__
        super().__init__(message)


class UsageError(RamalioError):
    """Invalid CLI syntax or arguments."""

    exit_code = ExitCode.USAGE_ERROR


class ConfigurationError(RamalioError):
    """Required configuration is absent or invalid.

    ``code`` is a stable, machine-readable identifier meant for tests and
    tooling.  It stays constant even if the human message wording changes.
    """

    exit_code = ExitCode.CONFIGURATION_ERROR
    code: str = "CONFIGURATION_ERROR"


class NotInGitRepositoryError(ConfigurationError):
    """The execution context does not resolve to a Git repository."""

    code = "NOT_IN_GIT_REPOSITORY"


class ProjectConfigNotFoundError(ConfigurationError):
    """The resolved repository root has no ``.ramalio.toml`` file."""

    code = "PROJECT_CONFIG_NOT_FOUND"


class ProjectConfigParseError(ConfigurationError):
    """``.ramalio.toml`` exists but is not syntactically valid TOML."""

    code = "PROJECT_CONFIG_PARSE_ERROR"


class ProjectConfigInvalidError(ConfigurationError):
    """``.ramalio.toml`` parses but violates the configuration contract."""

    code = "PROJECT_CONFIG_INVALID"


class TargetRegexInvalidError(ConfigurationError):
    """``[target].regex`` is absent, empty or does not compile (E1-S1 R1, R2).

    Detected while validating project configuration, before any lifecycle
    operation runs.
    """

    code = "TARGET_REGEX_INVALID"


class BranchPatternInvalidError(ConfigurationError):
    """``[branch].pattern`` is empty, misses ``{target}`` or has unknown
    placeholders (E1-S2 R11, R13).

    This is a configuration defect: the declared pattern itself is unusable,
    independently of any concrete candidate.
    """

    code = "BRANCH_PATTERN_INVALID"


class WorktreePatternInvalidError(ConfigurationError):
    """``[worktree].pattern`` is empty, misses ``{target}`` or has unknown
    placeholders (E1-S2 R12, R13).

    Like :class:`BranchPatternInvalidError`, this is a configuration defect in
    the declared pattern, not a per-candidate failure.
    """

    code = "WORKTREE_PATTERN_INVALID"


class TargetExampleInvalidError(ConfigurationError):
    """``[target].example`` is absent, empty or violates its own policy (R1, R6).

    A project ships an example that must itself satisfy the configured target
    policy; otherwise the configuration is rejected.
    """

    code = "TARGET_EXAMPLE_INVALID"


class CapabilityDuplicateError(ConfigurationError):
    """Two capabilities were registered under the same name (E4-S0 R2).

    A stable, unique name per capability is an invariant of the registry
    (INV-04); a duplicate registration is a defect in how the installation wired
    its capabilities together, surfaced as a configuration error.
    """

    code = "CAPABILITY_DUPLICATE"


class CapabilityUnknownError(ConfigurationError):
    """Configuration enables a capability the installation does not know (E4-S0 R13).

    The registry never loads arbitrary modules from configuration (INV-07/R4);
    an enabled-but-unregistered capability is an explicit failure rather than a
    silent no-op.
    """

    code = "CAPABILITY_UNKNOWN"


class CapabilityConfigInvalidError(ConfigurationError):
    """A capability's namespaced configuration is invalid (E4-S0 R12).

    Raised by a capability while validating its own ``[capabilities.<name>]``
    section.  The message carries the capability name and the specific defect.
    """

    code = "CAPABILITY_CONFIG_INVALID"


class ProcessDuplicateNameError(ConfigurationError):
    """Two managed process items share the same name (E4-S2 R2).

    Process items are addressed by name per project, so a duplicate name is a
    configuration defect.
    """

    code = "PROCESS_DUPLICATE_NAME"


class StateError(RamalioError):
    """Workspace state or identity does not allow the requested operation.

    ``code`` is a stable, machine-readable identifier meant for tests and
    tooling.  It stays constant even if the human message wording changes.
    """

    exit_code = ExitCode.STATE_ERROR
    code: str = "STATE_ERROR"


class TargetInvalidError(StateError):
    """A candidate target does not satisfy the effective project policy (R8).

    The human-facing message includes the received value and the configured
    example so the user can correct the input themselves (INV-05).  This spec
    never rewrites the input.
    """

    code = "TARGET_INVALID"


class TargetTooLongError(StateError):
    """A candidate target exceeds :data:`MAX_TARGET_LENGTH` (R12).

    The limit protects the CLI, logs, derived paths and diagnostics, so it is a
    product-level bound rather than a project-level policy.
    """

    code = "TARGET_TOO_LONG"


class TargetNormalizationFailedError(StateError):
    """A normalization rule cannot be applied unambiguously (E1-S2 R7).

    Rather than inventing a canonical form, normalization fails so the user can
    correct the raw input themselves (INV-04, conservative behavior).
    """

    code = "TARGET_NORMALIZATION_FAILED"


class TargetNormalizationEmptyError(StateError):
    """Normalization collapsed the raw value into an empty string (E1-S2 R8).

    Detected before a :class:`Target` is built so an empty identity never
    reaches validation or naming.
    """

    code = "TARGET_NORMALIZATION_EMPTY"


class DerivedBranchInvalidError(StateError):
    """The branch name derived from a valid target is not a safe Git ref (R14).

    E1-S2 validates the ref shape read-only; it never creates the branch.
    """

    code = "DERIVED_BRANCH_INVALID"


class DerivedWorktreePathInvalidError(StateError):
    """The worktree path derived from a valid target is structurally unsafe (R15).

    Covers empty paths, traversal escaping the configured boundary and patterns
    resolving to the repository root.  Deep boundary hardening lands in E7-S2;
    E1-S2 rejects obviously-unsafe derivations without touching the filesystem.
    """

    code = "DERIVED_WORKTREE_PATH_INVALID"


class GitRepositoryInvalidError(ConfigurationError):
    """The Git context is not a usable repository for lifecycle work (E2-S0 R2).

    Distinct from :class:`NotInGitRepositoryError`: the root may resolve yet the
    repository is unusable (e.g. bare, corrupted) for the operations the Git
    boundary requires.
    """

    code = "GIT_REPOSITORY_INVALID"


class BaseBranchNotFoundError(StateError):
    """``project.base_branch`` does not exist as a usable local ref (E2-S0 R3).

    E2 never performs an implicit ``fetch``; a missing base branch is reported
    as-is so the user can create or fetch it themselves (INV-14).
    """

    code = "BASE_BRANCH_NOT_FOUND"


class BranchAlreadyExistsError(StateError):
    """The branch derived for a target already exists (E2-S0 R9).

    E2-S0 only distinguishes the fact; deciding whether it is adoptable belongs
    to later specs (7.6).
    """

    code = "BRANCH_ALREADY_EXISTS"


class BranchAlreadyCheckedOutError(StateError):
    """The target branch is already checked out in another worktree (E2-S0 R11)."""

    code = "BRANCH_ALREADY_CHECKED_OUT"


class WorktreePathAlreadyExistsError(StateError):
    """The derived worktree path already exists on disk (E2-S0 R10)."""

    code = "WORKTREE_PATH_ALREADY_EXISTS"


class WorktreeAlreadyRegisteredError(StateError):
    """The derived path is already registered as a Git worktree (E2-S0 R10)."""

    code = "WORKTREE_ALREADY_REGISTERED"


class WorkspaceAlreadyExistsError(StateError):
    """A managed workspace for the target already exists as a whole (E2-S1 R14).

    Distinct from the per-resource ``*_ALREADY_*`` errors: it signals that a
    previous successful ``init`` already produced the branch *and* its worktree,
    so a repeated identical ``init`` is a controlled no-op failure rather than a
    partial collision.  Idempotency is expressed as a failure, never as a silent
    second creation (INV-02, INV-04).
    """

    code = "WORKSPACE_ALREADY_EXISTS"


class AdoptBranchNotFoundError(StateError):
    """No branch matches the identity derived for the target (E2-S2 R4).

    ``adopt`` incorporates *existing* work; when the derived branch does not
    exist there is nothing to adopt.  The message guides the user toward
    ``init`` without creating any resource (INV-01).
    """

    code = "ADOPT_BRANCH_NOT_FOUND"


class AdoptBranchInOtherWorktreeError(StateError):
    """The derived branch is checked out in a worktree at a non-canonical path
    (E2-S2 R5).

    ``adopt`` never moves or deletes an existing worktree to force compatibility
    (INV-06); it fails conservatively so the user resolves it explicitly.
    """

    code = "ADOPT_BRANCH_IN_OTHER_WORKTREE"


class AdoptWorktreePathConflictError(StateError):
    """The canonical worktree path exists on disk but is not the expected
    managed worktree (E2-S2 R6).

    An ordinary directory or an unrelated checkout occupies the path.  ``adopt``
    never deletes or modifies that path (INV-02).
    """

    code = "ADOPT_WORKTREE_PATH_CONFLICT"


class AdoptWorktreeBranchMismatchError(StateError):
    """A worktree is registered at the canonical path but uses a different
    branch than the one derived for the target (E2-S2 R7)."""

    code = "ADOPT_WORKTREE_BRANCH_MISMATCH"


class AdoptWorktreeDetachedError(StateError):
    """The worktree registered at the canonical path has a detached HEAD
    (E2-S2 R8).

    A detached worktree is not compatible with an identity that requires the
    derived branch to be checked out.
    """

    code = "ADOPT_WORKTREE_DETACHED"


class SafetyError(RamalioError):
    """A safety invariant blocks an otherwise understood operation."""

    exit_code = ExitCode.SAFETY_BLOCKED


class WorkspaceNotFoundError(StateError):
    """No managed workspace (branch nor worktree) exists for the target
    (E2-S3 R2).

    ``destroy`` never treats absence as a silent success; it reports this
    explicitly so a second destroy is a controlled, diagnosable no-op (R19).
    """

    code = "WORKSPACE_NOT_FOUND"


class DestroyWorktreeMismatchError(StateError):
    """The canonical worktree path is registered but uses a different branch
    than the one derived for the target (E2-S3 R4)."""

    code = "DESTROY_WORKTREE_MISMATCH"


class DestroyBranchInOtherWorktreeError(StateError):
    """The derived branch is checked out in a worktree at a non-canonical path
    (E2-S3 R5).

    ``destroy`` will not remove a worktree that is not the canonical one for the
    target (INV-02/INV-03).
    """

    code = "DESTROY_BRANCH_IN_OTHER_WORKTREE"


class DestroyProtectedBranchError(StateError):
    """The derived branch collides with ``project.base_branch`` (E2-S3 R14).

    ``destroy`` never removes the base branch, even if a misconfiguration
    derives it for a target (INV-04).
    """

    code = "DESTROY_PROTECTED_BRANCH"


class DestroyBlockedDirtyError(SafetyError):
    """Local work in the target worktree blocks destruction (E2-S3 R6/R7).

    Modeled as a safety block because it protects against silent loss of local
    work (INV-01).  Covers both uncommitted tracked changes and untracked files;
    ``destroy`` never auto-commits or stashes to work around it (INV-06).
    """

    code = "DESTROY_BLOCKED_DIRTY"


class WorkspaceNotActiveError(StateError):
    """A ``start``/``stop`` target has no full, operable workspace (E3-S2 R4).

    The branch exists but there is no worktree to operate on (BRANCH_ONLY), so
    there is nothing to start or stop.  Guides the user toward ``adopt`` without
    recreating anything (INV-02).
    """

    code = "WORKSPACE_NOT_ACTIVE"


class WorkspaceInconsistentError(StateError):
    """A ``start``/``stop`` target is in an anomalous state (E3-S2 R5).

    INCONSISTENT / DETACHED / PRUNABLE workspaces are not operationally
    addressable; ``start``/``stop`` fail closed and suggest inspection rather
    than attempting any repair (INV-02).
    """

    code = "WORKSPACE_INCONSISTENT"


class OperationError(RamalioError):
    """An expected operation/dependency failure occurred."""

    exit_code = ExitCode.OPERATION_FAILED


class GitCommandError(OperationError):
    """A Git command executed by the boundary failed unexpectedly (E2-S0 R2, R6).

    Wraps the failing argv and captured ``stderr`` so callers get a stable
    domain error instead of raw subprocess details.  Used for failures that are
    not modeled by a more specific domain error above (INV-06).
    """

    code = "GIT_COMMAND_FAILED"

    def __init__(
        self,
        message: str,
        *,
        args: tuple[str, ...] | None = None,
        returncode: int | None = None,
        stderr: str | None = None,
    ) -> None:
        super().__init__(message)
        self.args_run = args
        self.returncode = returncode
        self.stderr = stderr


class InitGitOperationFailedError(OperationError):
    """A mutating Git step of ``init`` failed (E2-S1 7.4).

    Raised when creating the branch/worktree fails for a reason not covered by a
    more specific precondition error.  Any partial mutation this operation made
    is rolled back before the error surfaces (INV-04, R11).  The original Git
    stderr is preserved as an internal diagnostic cause, never merged into the
    public CLI output (R16).
    """

    code = "INIT_GIT_OPERATION_FAILED"


class InitPostconditionFailedError(OperationError):
    """``init`` created resources but could not verify a coherent result (R9, R12).

    Git reported an inconsistent postcondition (missing branch/worktree, wrong
    branch association or path mismatch).  The operation attempts to roll back
    the resources it created before reporting this failure (R12).
    """

    code = "INIT_POSTCONDITION_FAILED"


class InitRollbackIncompleteError(OperationError):
    """Rollback of an ``init`` failure could not fully undo owned mutations (R11).

    Surfaced *in addition to* the original failure so a partially-cleaned state
    is never silently reported as success and stays diagnosable (INV-05, INV-06).
    ``cause_code`` carries the stable code of the original failure that triggered
    the rollback.
    """

    code = "INIT_ROLLBACK_INCOMPLETE"

    def __init__(self, message: str, *, cause_code: str | None = None) -> None:
        super().__init__(message)
        self.cause_code = cause_code



class AdoptGitOperationFailedError(OperationError):
    """A mutating Git step of ``adopt`` failed (E2-S2 R13).

    Raised when creating the branch-only worktree fails for a reason not covered
    by a more specific precondition error.  Any worktree this operation created
    is rolled back before the error surfaces; the preexisting branch is never
    touched (INV-05, R13, R15).
    """

    code = "ADOPT_GIT_OPERATION_FAILED"


class AdoptPostconditionFailedError(OperationError):
    """``adopt`` created a worktree but could not verify a coherent result
    (E2-S2 R11, R13).

    The operation rolls back only the worktree it created (never the branch)
    before reporting this failure.
    """

    code = "ADOPT_POSTCONDITION_FAILED"


class AdoptRollbackIncompleteError(OperationError):
    """Rollback of an ``adopt`` failure could not fully retire the worktree it
    created (E2-S2 R13).

    Surfaced *in addition to* the original failure so a partially-cleaned state
    is never silently reported as success and stays diagnosable (INV-005,
    INV-006).  ``cause_code`` carries the stable code of the original failure.
    The preexisting branch is never part of rollback (R15).
    """

    code = "ADOPT_ROLLBACK_INCOMPLETE"

    def __init__(self, message: str, *, cause_code: str | None = None) -> None:
        super().__init__(message)
        self.cause_code = cause_code



class LifecycleRollbackIncompleteError(OperationError):
    """A lifecycle transaction rollback could not fully compensate every owned,
    mutated resource (E7-S0 R6/R7/R16).

    Shared across ``init``, ``start``, ``stop`` and ``destroy``: raised in
    addition to the primary failure whenever :meth:`LifecycleTransaction.rollback`
    reports ``ROLLBACK_PARTIAL`` (a compensation itself failed) or
    ``ROLLBACK_NOT_SAFE`` (an owned mutation had no safe compensation, e.g. an
    irreversible Git removal or a capability that declared none).  The partial
    state is never reported as a clean success and stays diagnosable
    (INV-005/INV-006); nothing is recreated or force-cleaned as a side effect of
    reporting it (R13/R15).
    """

    code = "LIFECYCLE_ROLLBACK_INCOMPLETE"

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        outcome: str,
        cause_code: str | None = None,
        rollback_errors: tuple[str, ...] = (),
        unsafe_resources: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.outcome = outcome
        self.cause_code = cause_code
        self.rollback_errors = rollback_errors
        self.unsafe_resources = unsafe_resources



class DestroyWorktreeRemoveFailedError(OperationError):
    """Git could not remove the target worktree (E2-S3 R16).

    When worktree removal fails, ``destroy`` does not attempt branch deletion
    and preserves the diagnostic.  ``--force`` is never used in the normal flow
    (R9/R13).
    """

    code = "DESTROY_WORKTREE_REMOVE_FAILED"


class DestroyPostconditionFailedError(OperationError):
    """``destroy`` could not verify the expected final Git state (E2-S3 R7/R18).

    The registry/refs disagree with what would be reported, so the operation
    fails closed rather than presenting a partial state as a clean success
    (INV-07).
    """

    code = "DESTROY_POSTCONDITION_FAILED"



class CapabilityHookFailedError(OperationError):
    """A capability lifecycle hook failed (E4-S1 R16).

    Wraps an unexpected exception raised by a capability during a lifecycle
    event into a stable domain error, carrying the capability name and event so
    the failure is diagnosable.  The lifecycle decides whether to block (before_*)
    or compensate/report (after_*).
    """

    code = "CAPABILITY_HOOK_FAILED"

    def __init__(
        self,
        message: str,
        *,
        capability: str | None = None,
        event: str | None = None,
    ) -> None:
        super().__init__(message)
        self.capability = capability
        self.event = event



class ProcessOwnershipMismatchError(StateError):
    """Recorded process metadata no longer identifies the owned process (E4-S2 R11).

    The PID now belongs to a different process (PID reuse) or cannot be
    verified.  The terminator refuses to send any signal (INV-03).
    """

    code = "PROCESS_OWNERSHIP_MISMATCH"


class ProcessOperationFailedError(OperationError):
    """A managed-process operation (start/stop) failed (E4-S2 R8/R10).

    Wraps launch/termination failures not covered by a more specific error.
    """

    code = "PROCESS_OPERATION_FAILED"


class ProcessStartRollbackIncompleteError(OperationError):
    """A partial process start could not be fully rolled back (audit H8).

    ``_start_items`` runs its own bounded mini-lifecycle: it starts items one by
    one and, on a launch failure, stops the ones it already started.  If that
    internal cleanup itself fails, the resulting partial state must be
    *structurally* diagnosable — mirroring the LifecycleTransaction rollback
    outcomes (E7-S0 ``primary_error`` / ``rollback_errors`` / unsafe resources)
    — instead of being flattened into a single opaque string.  This error
    carries the original launch failure plus the per-item cleanup failures and
    the processes left running, so the failure enters the same rollback-incomplete
    semantics as every other lifecycle operation (INV-005/INV-006).
    """

    code = "PROCESS_START_ROLLBACK_INCOMPLETE"

    def __init__(
        self,
        message: str,
        *,
        primary_error: BaseException | None = None,
        cleanup_errors: tuple[str, ...] = (),
        leftover_processes: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.primary_error = primary_error
        self.cleanup_errors = cleanup_errors
        self.leftover_processes = leftover_processes



class TmuxSessionOwnershipError(StateError):
    """A tmux session with the derived name cannot be attributed to the target
    (E5-S0 R10).

    A preexisting session shares the derived name but lacks the workspace
    ownership marker, so the capability refuses to reuse or kill it.
    """

    code = "TMUX_SESSION_OWNERSHIP"


class TmuxOperationFailedError(OperationError):
    """A tmux operation failed unexpectedly (E5-S0)."""

    code = "TMUX_OPERATION_FAILED"



class IntegrationNotFoundError(ConfigurationError):
    """A requested integration name is not registered (E5-S1 R5)."""

    code = "INTEGRATION_NOT_FOUND"


class IntegrationDisabledError(StateError):
    """A known integration is not enabled in the project configuration (E5-S1 R6)."""

    code = "INTEGRATION_DISABLED"


class IntegrationUnavailableError(OperationError):
    """A known, enabled integration's command/binary is not available (E5-S1 R7)."""

    code = "INTEGRATION_UNAVAILABLE"


class IntegrationConfigInvalidError(ConfigurationError):
    """An integration's namespaced configuration is invalid (E5-S1 R1/R3)."""

    code = "INTEGRATION_CONFIG_INVALID"


class IntegrationOpenFailedError(OperationError):
    """Opening an integration failed after the workspace was ready (E5-S1 R9).

    Modeled as an operation failure that never rolls back the Git workspace; the
    caller reports a partial result instead (INV: failure isolation).
    """

    code = "INTEGRATION_OPEN_FAILED"



class RuntimeDriverUnknownError(ConfigurationError):
    """The configured runtime driver name is not registered (E6-S0 R7)."""

    code = "RUNTIME_DRIVER_UNKNOWN"


class PartialMutationError(OperationError):
    """An operation error that MAY have mutated a resource before failing (H4).

    E7-S0 requires that a mutation which happens *before* an exception still
    enters the transactional model.  A driver/provider that mutates and then
    fails raises a subclass of this error declaring:

    * ``changed`` — True (a mutation happened), False (none), or None (UNKNOWN,
      could not observe); the caller applies its fail-closed heuristic on None.
    * ``resource_identity`` — an identifier for the possibly-mutated resource.
    * ``compensation_available`` — whether the capability can compensate it.

    The hook runner reads these to record a transaction step for the partial
    mutation *before* propagating the failure, so rollback can compensate it
    (or classify it NOT_SAFE) instead of losing the fact that it happened.
    """

    def __init__(
        self,
        message: str,
        *,
        changed: bool | None = None,
        resource_identity: str | None = None,
        compensation_available: bool = False,
    ) -> None:
        super().__init__(message)
        self.changed = changed
        self.resource_identity = resource_identity
        self.compensation_available = compensation_available


class RuntimeStartFailedError(PartialMutationError):
    """The runtime driver failed to start (E6-S0 R7).

    ``docker compose up`` may start some services before failing, so this
    carries the partial-mutation contract (audit H4).
    """

    code = "RUNTIME_START_FAILED"


class RuntimeStopFailedError(PartialMutationError):
    """The runtime driver failed to stop (E6-S0 R7)."""

    code = "RUNTIME_STOP_FAILED"


class RuntimeStatusFailedError(OperationError):
    """The runtime driver failed to report status (E6-S0 R7)."""

    code = "RUNTIME_STATUS_FAILED"


class RuntimeCleanupFailedError(PartialMutationError):
    """The runtime driver failed to clean up its resources (E6-S0 R7)."""

    code = "RUNTIME_CLEANUP_FAILED"



class PortRangeExhaustedError(StateError):
    """No free port is available in the configured range (E6-S1 R7)."""

    code = "PORT_RANGE_EXHAUSTED"


class PortConfigInvalidError(ConfigurationError):
    """The ports configuration is invalid (E6-S1 R2)."""

    code = "PORT_CONFIG_INVALID"



class TunnelProviderUnknownError(ConfigurationError):
    """The configured tunnel provider name is not registered (E6-S3 R1)."""

    code = "TUNNEL_PROVIDER_UNKNOWN"


class TunnelStartFailedError(PartialMutationError):
    """The tunnel provider failed to start an exposure (E6-S3 R7/R15).

    Starting a tunnel may launch a process before failing to verify/persist it,
    so this carries the partial-mutation contract (audit H4).
    """

    code = "TUNNEL_START_FAILED"


class TunnelStopFailedError(OperationError):
    """The tunnel provider failed to stop an exposure (E6-S3 R9)."""

    code = "TUNNEL_STOP_FAILED"



class LockTimeoutError(OperationError):
    """A lock could not be acquired within the timeout (E7-S1 R8).

    Signals contention on a shared resource (same target/branch/path/port pool);
    the operation performs no mutation after a lock timeout.
    """

    code = "LOCK_TIMEOUT"



class ConfigVersionUnsupportedError(ConfigurationError):
    """The configuration declares a schema version this CLI cannot support
    (E9-S1 R12).

    Fail-closed: a newer-than-supported schema (or a malformed version) is never
    interpreted optimistically; the user must upgrade the CLI or fix the
    version (INV-05/R17).
    """

    code = "CONFIG_VERSION_UNSUPPORTED"



class BootstrapReadinessFailedError(OperationError):
    """A bootstrap readiness check failed (E10-S2 R5/R7).

    Raised for a failed writable probe (before dependency install) or a missing
    required artifact (after install).  Classified as an operation failure, not
    a provider/Composer failure, so the diagnostics point at readiness rather
    than blaming the dependency tool.
    """

    code = "BOOTSTRAP_READINESS_FAILED"


class BootstrapProviderFailedError(PartialMutationError):
    """The bootstrap dependency provider failed (E10-S2 R6/§6).

    ``composer install`` may mutate the dependency tree before failing, so this
    carries the partial-mutation contract: the capability cannot prove file-by-
    file ownership, so it never fakes a full rollback; the failure stays
    diagnosable and the transaction records the partial mutation.
    """

    code = "BOOTSTRAP_PROVIDER_FAILED"



class DataReadinessTimeoutError(OperationError):
    """A data service did not become ready within the timeout (E10-S3 R6)."""

    code = "DATA_READINESS_TIMEOUT"


class DataProvisioningFailedError(PartialMutationError):
    """PostgreSQL data provisioning failed (E10-S3 R7/R8/R12).

    A restore may partially apply before failing, so this carries the partial-
    mutation contract.  The provider never touches the source during rollback;
    a partial restore left in a runtime the operation does not own is reported
    as incomplete/degraded rather than destroyed (R12).
    """

    code = "DATA_PROVISIONING_FAILED"
