"""Tests for the integration contract, registry and --open flow (E5-S1)."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    IntegrationDisabledError,
    IntegrationNotFoundError,
    IntegrationUnavailableError,
)
from ramalio.core.result import ExitCode
from ramalio.integrations import (
    BaseIntegration,
    IntegrationContext,
    IntegrationRegistry,
    OpenIntegrationService,
    OpenResult,
)


def _config_body(integrations: str = "") -> str:
    return f"""
[project]
name = "simple-git"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{{target}}"

[branch]
pattern = "{{target}}"
{integrations}
"""


@pytest.fixture
def project(git_repo_with_commit: Path, write_config) -> Path:
    body = _config_body(
        '\n[integrations.faketool]\nenabled = true\ncommand = ["sleep"]\n'
    )
    write_config(git_repo_with_commit, body)
    return git_repo_with_commit


class _FakeIntegration(BaseIntegration):
    integration_name = "faketool"

    def __init__(self) -> None:
        self.opened_in: Path | None = None

    def is_available(self, context: IntegrationContext) -> bool:
        return True

    def open(self, context: IntegrationContext) -> OpenResult:
        self.opened_in = context.worktree_path
        return OpenResult(name=self.name, opened=True, summary="opened fake")


def _ctx(project_root: Path, target: str = "feat-a") -> IntegrationContext:
    config = resolve_project_config(project_root)
    return IntegrationContext(
        config=config,
        target=target,
        worktree_path=(project_root / ".local-wt" / target).resolve(),
    )


# --- registry --------------------------------------------------------------


def test_unknown_integration_not_found(project: Path) -> None:
    service = OpenIntegrationService(
        resolve_project_config(project),
        registry=IntegrationRegistry.with_integrations([_FakeIntegration()]),
    )
    with pytest.raises(IntegrationNotFoundError):
        service.open(
            name="does-not-exist",
            target="feat-a",
            worktree_path=project / ".local-wt" / "feat-a",
        )


def test_disabled_integration(git_repo_with_commit: Path, write_config) -> None:
    body = _config_body(
        '\n[integrations.faketool]\nenabled = false\ncommand = ["sleep"]\n'
    )
    write_config(git_repo_with_commit, body)
    service = OpenIntegrationService(
        resolve_project_config(git_repo_with_commit),
        registry=IntegrationRegistry.with_integrations([_FakeIntegration()]),
    )
    with pytest.raises(IntegrationDisabledError):
        service.open(
            name="faketool",
            target="feat-a",
            worktree_path=git_repo_with_commit / ".local-wt" / "feat-a",
        )


class _UnavailableIntegration(BaseIntegration):
    integration_name = "faketool"

    def is_available(self, context: IntegrationContext) -> bool:
        return False

    def open(self, context: IntegrationContext) -> OpenResult:  # pragma: no cover
        raise AssertionError("should not be called")


def test_unavailable_integration(project: Path) -> None:
    service = OpenIntegrationService(
        resolve_project_config(project),
        registry=IntegrationRegistry.with_integrations([_UnavailableIntegration()]),
    )
    with pytest.raises(IntegrationUnavailableError):
        service.open(
            name="faketool",
            target="feat-a",
            worktree_path=project / ".local-wt" / "feat-a",
        )


def test_open_uses_worktree_cwd(project: Path) -> None:
    fake = _FakeIntegration()
    service = OpenIntegrationService(
        resolve_project_config(project),
        registry=IntegrationRegistry.with_integrations([fake]),
    )
    wt = (project / ".local-wt" / "feat-a").resolve()
    result = service.open(name="faketool", target="feat-a", worktree_path=wt)
    assert result.opened is True
    assert fake.opened_in == wt


# --- CLI --open integration ------------------------------------------------


def test_cli_init_without_open_unchanged(project: Path, monkeypatch) -> None:
    from ramalio.cli import main

    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["init", "feat-plain"], stdout=stdout, stderr=stderr)
    assert code == ExitCode.OK
    assert "target: feat-plain" in stdout.getvalue()
    assert "opened:" not in stdout.getvalue()


def test_cli_init_open_unknown_is_partial(project: Path, monkeypatch) -> None:
    # Default integration registry is empty -> unknown tool. Workspace must
    # still be created (failure isolation, R9).
    from ramalio.cli import main
    from ramalio.git.repository import GitRepository

    monkeypatch.chdir(project)
    stdout, stderr = StringIO(), StringIO()
    code = main(["init", "feat-open", "--open", "faketool"], stdout=stdout, stderr=stderr)

    # Unknown integration -> non-zero, but workspace exists.
    assert code != ExitCode.OK
    assert "target: feat-open" in stdout.getvalue()
    assert "could not open" in stderr.getvalue()
    assert GitRepository.from_root(project).branch_exists("feat-open")
