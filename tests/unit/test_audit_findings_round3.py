"""Adversarial regression tests for the third (final, scoped) audit round.

Two findings, both strictly within E7 scope:

* H1 (E7-S0): a partial mutation with UNKNOWN ownership (``changed is None``)
  must NEVER be compensated blindly.  It must be recorded as a non-compensable
  step so rollback is ROLLBACK_NOT_SAFE and the resource is preserved.
* H2 (E7-S2 R14): external subprocess stderr must be sanitized before being
  embedded in an error, so secrets are not leaked in diagnostics.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ramalio.capabilities import CapabilityRegistry
from ramalio.capabilities.runtime.base import (
    RuntimeResult,
    RuntimeState,
    RuntimeWorkspace,
)
from ramalio.capabilities.runtime.capability import RuntimeCapability
from ramalio.capabilities.runtime.docker_compose import DockerComposeDriver
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    LifecycleRollbackIncompleteError,
    RuntimeStartFailedError,
)
from ramalio.core.init import InitWorkspaceService
from ramalio.core.naming import ResolvedWorkspaceIdentity
from ramalio.core.target import Target


_CONFIG_BODY = """
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "{target}"
"""


# ---------------------------------------------------------------------------
# H1 — UNKNOWN-ownership partial mutation is NOT_SAFE, never blindly compensated
# ---------------------------------------------------------------------------


class _UnknownMutationRuntimeDriver:
    """start() may have mutated but cannot prove ownership: it declares
    ``changed=None`` (UNKNOWN) and, defensively, even advertises a compensation.

    The runner MUST ignore the offered compensation for a changed-UNKNOWN
    mutation and record a non-compensable (unsafe) step instead, so rollback
    never calls stop() on a runtime this start may not own."""

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    @property
    def name(self) -> str:
        return "fake"

    def doctor(self, workspace):
        return ()

    def status(self, workspace):
        # Pre-start status cannot be observed reliably.
        from ramalio.core.errors import RuntimeStatusFailedError

        raise RuntimeStatusFailedError("status unavailable")

    def start(self, workspace):
        self._calls.append("start")
        raise RuntimeStartFailedError(
            "mutated but ownership unknown",
            changed=None,  # UNKNOWN
            resource_identity="runtime:fake",
            compensation_available=True,  # even if offered, must be ignored
        )

    def stop(self, workspace):
        self._calls.append("stop")
        return RuntimeResult(RuntimeState.STOPPED, "stopped", changed=True)

    def cleanup(self, workspace):
        self._calls.append("cleanup")
        return RuntimeResult(RuntimeState.STOPPED, "down", changed=False)


def test_h1_unknown_ownership_is_not_safe_and_not_compensated(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _CONFIG_BODY + '\n[capabilities.runtime]\ndriver = "fake"\n',
    )
    from ramalio.core.startstop import StartWorkspaceService

    calls: list[str] = []
    driver = _UnknownMutationRuntimeDriver(calls)
    registry = CapabilityRegistry.with_capabilities(
        [RuntimeCapability(drivers={"fake": lambda _o, _c=None: driver})]
    )
    cfg = resolve_project_config(git_repo_with_commit)
    InitWorkspaceService(cfg, registry=registry).run("feat-r3h1")
    calls.clear()

    with pytest.raises(LifecycleRollbackIncompleteError) as exc:
        StartWorkspaceService(cfg, registry=registry).run("feat-r3h1")

    # The UNKNOWN mutation must be surfaced as an unsafe (non-compensable)
    # resource...
    assert exc.value.outcome == "ROLLBACK_NOT_SAFE"
    assert exc.value.unsafe_resources
    # ...and stop() must NEVER have been called on a runtime we don't own.
    assert "stop" not in calls, (
        "a changed-UNKNOWN partial mutation must not be blindly compensated"
    )


# ---------------------------------------------------------------------------
# H2 — external stderr is sanitized before being surfaced in an error
# ---------------------------------------------------------------------------


class _LeakyDockerRunner:
    """A docker runner whose failing command emits a secret on stderr."""

    def __init__(self, *, fail: str) -> None:
        self._fail = fail  # which subcommand fails: "up" / "stop" / "down"
        self.calls: list[tuple[str, ...]] = []

    @property
    def available(self) -> bool:
        return True

    def compose_available(self) -> bool:
        return True

    def compose(self, project, compose_file, *args, cwd, env=None, extra_files=()):
        self.calls.append(tuple(args))
        if args and args[0] == "ps":
            # Report no running / no resources so start proceeds to `up`.
            return subprocess.CompletedProcess([], 0, "", "")
        if args and args[0] == self._fail:
            return subprocess.CompletedProcess(
                [], 1, "", "ZROK_TOKEN=super-secret-value boom"
            )
        return subprocess.CompletedProcess([], 0, "", "")


def _workspace(tmp_path: Path, target: str = "alpha") -> RuntimeWorkspace:
    wt = tmp_path / target
    wt.mkdir(exist_ok=True)
    from pathlib import PurePosixPath

    identity = ResolvedWorkspaceIdentity(
        target=Target.from_trusted(target),
        branch_name=target,
        worktree_path=PurePosixPath(".local-wt") / target,
    )
    return RuntimeWorkspace(
        target=target, worktree_path=wt, identity=identity, repository_root=tmp_path
    )


@pytest.mark.parametrize("subcmd", ["up", "stop", "down"])
def test_h2_stderr_secret_is_redacted_in_errors(tmp_path: Path, subcmd: str) -> None:
    from ramalio.core.errors import (
        RuntimeCleanupFailedError,
        RuntimeStartFailedError,
        RuntimeStopFailedError,
    )

    runner = _LeakyDockerRunner(fail=subcmd)
    driver = DockerComposeDriver({}, runner=runner, project_name="proj")
    ws = _workspace(tmp_path)

    op = {"up": driver.start, "stop": driver.stop, "down": driver.cleanup}[subcmd]
    err_type = {
        "up": RuntimeStartFailedError,
        "stop": RuntimeStopFailedError,
        "down": RuntimeCleanupFailedError,
    }[subcmd]

    with pytest.raises(err_type) as exc:
        op(ws)

    message = str(exc.value)
    assert "super-secret-value" not in message, f"secret leaked: {message!r}"
    assert "ZROK_TOKEN=***" in message, (
        f"expected the secret assignment to be masked, got: {message!r}"
    )


def test_h2_redact_diagnostic_masks_common_markers() -> None:
    from ramalio.security import redact_diagnostic

    text = (
        "PASSWORD=hunter2 API_KEY: abc123 SECRET=zzz AWS_CREDENTIAL=q "
        "PORT=8080 host=localhost"
    )
    out = redact_diagnostic(text)
    for secret in ("hunter2", "abc123", "zzz", "AWS_CREDENTIAL=q".split("=")[1]):
        assert secret not in out
    # Non-secret assignments are preserved.
    assert "PORT=8080" in out
    assert "host=localhost" in out
