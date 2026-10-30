"""Tests for the initial integration adapters: kiro/vscode/codex/claude (E5-S2)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.config.loader import resolve_project_config
from ramalio.integrations import IntegrationContext, IntegrationRegistry
from ramalio.integrations.adapters import (
    ClaudeIntegration,
    CodexIntegration,
    KiroIntegration,
    VsCodeIntegration,
    initial_integrations,
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


def _ctx(project_root: Path, integrations: str, target: str = "feat-a") -> IntegrationContext:
    (project_root / ".ramalio.toml").write_text(
        _config_body(integrations), encoding="utf-8"
    )
    config = resolve_project_config(project_root)
    return IntegrationContext(
        config=config,
        target=target,
        worktree_path=(project_root / ".local-wt" / target).resolve(),
    )


# --- names and defaults ----------------------------------------------------


def test_adapter_names() -> None:
    assert {i.name for i in initial_integrations()} == {
        "kiro",
        "vscode",
        "codex",
        "claude",
    }


def test_vscode_default_command() -> None:
    assert VsCodeIntegration().default_command == ("code", ".")


def test_defaults_have_no_personal_paths() -> None:
    for integration in initial_integrations():
        for token in integration.default_command:
            assert "/home/" not in token
            assert not token.startswith("/")


# --- command resolution & override -----------------------------------------


def test_config_overrides_default(git_repo_with_commit: Path) -> None:
    ctx = _ctx(
        git_repo_with_commit,
        '\n[integrations.kiro]\nenabled = true\ncommand = ["kiro-cli", "--v3"]\n',
    )
    kiro = KiroIntegration()
    assert kiro._command(ctx) == ["kiro-cli", "--v3"]


def test_default_used_when_no_command(git_repo_with_commit: Path) -> None:
    ctx = _ctx(git_repo_with_commit, "\n[integrations.codex]\nenabled = true\n")
    assert CodexIntegration()._command(ctx) == ["codex"]


# --- registry resolves each adapter ----------------------------------------


def test_registry_resolves_each(git_repo_with_commit: Path) -> None:
    registry = IntegrationRegistry.with_integrations(initial_integrations())
    for name in ("kiro", "vscode", "codex", "claude"):
        assert registry.get(name) is not None


# --- independent enablement + doctor ---------------------------------------


def test_doctor_reports_enabled_unavailable(git_repo_with_commit: Path) -> None:
    from ramalio.core.doctor import CheckStatus, DoctorService

    (git_repo_with_commit / ".ramalio.toml").write_text(
        _config_body(
            '\n[integrations.claude]\nenabled = true\n'
            'command = ["definitely-not-a-real-binary-xyz"]\n'
        ),
        encoding="utf-8",
    )
    report = DoctorService(start=git_repo_with_commit).run()
    claude = [r for r in report.results if r.check_id == "INTEGRATION_CLAUDE"]
    assert claude and claude[0].status == CheckStatus.FAIL


def test_doctor_ignores_disabled_integration(git_repo_with_commit: Path) -> None:
    from ramalio.core.doctor import DoctorService

    (git_repo_with_commit / ".ramalio.toml").write_text(
        _config_body('\n[integrations.vscode]\nenabled = false\n'),
        encoding="utf-8",
    )
    report = DoctorService(start=git_repo_with_commit).run()
    # Disabled integration contributes no check (R8).
    assert not [r for r in report.results if r.check_id == "INTEGRATION_VSCODE"]


# --- open via --open resolves the right adapter ----------------------------


def test_open_resolves_adapter(git_repo_with_commit: Path) -> None:
    # Use 'sleep' as an available stand-in command for kiro to prove open works
    # and resolves the kiro adapter through the default registry.
    ctx = _ctx(
        git_repo_with_commit,
        '\n[integrations.kiro]\nenabled = true\ncommand = ["sleep", "0.1"]\n',
    )
    from ramalio.integrations import OpenIntegrationService

    service = OpenIntegrationService(ctx.config)
    result = service.open(
        name="kiro",
        target="feat-a",
        worktree_path=ctx.worktree_path
        if ctx.worktree_path.exists()
        else git_repo_with_commit,
    )
    assert result.opened is True
    assert result.name == "kiro"
