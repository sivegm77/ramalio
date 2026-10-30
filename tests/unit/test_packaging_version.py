"""Tests for packaging, version and config schema compatibility (E9-S1)."""

from __future__ import annotations

import tomllib
from io import StringIO
from pathlib import Path

import pytest

from ramalio import SUPPORTED_CONFIG_SCHEMA, __version__
from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import ConfigVersionUnsupportedError
from ramalio.core.result import ExitCode

_BASE = """
[project]
name = "pkg-test"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "{target}"
"""


# --- version single source of truth (R4/AC-02) ----------------------------


def test_version_single_source() -> None:
    pyproject = (
        Path(__file__).resolve().parents[2] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    data = tomllib.loads(pyproject)
    # Version is derived dynamically from the package, not duplicated.
    assert "version" in data["project"].get("dynamic", [])
    assert data["tool"]["setuptools"]["dynamic"]["version"]["attr"] == (
        "ramalio.__version__"
    )


def test_cli_version_reports(monkeypatch) -> None:
    stdout, stderr = StringIO(), StringIO()
    code = main(["--version"], stdout=stdout, stderr=stderr)
    assert code == 0
    assert __version__ in stdout.getvalue()


def test_entry_point_declared() -> None:
    pyproject = (
        Path(__file__).resolve().parents[2] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    data = tomllib.loads(pyproject)
    assert data["project"]["scripts"]["ramalio"] == "ramalio.cli:main"


def test_no_runtime_dependencies() -> None:
    # Installing the engine must not pull external tools (AC-11/INV-06).
    pyproject = (
        Path(__file__).resolve().parents[2] / "pyproject.toml"
    ).read_text(encoding="utf-8")
    data = tomllib.loads(pyproject)
    assert data["project"]["dependencies"] == []


# --- config schema compatibility (R11/R12/AC-07/AC-08) ---------------------


def test_config_without_meta_defaults(git_repo_with_commit: Path, write_config) -> None:
    write_config(git_repo_with_commit, _BASE)
    config = resolve_project_config(git_repo_with_commit)
    assert config.meta.schema_version == SUPPORTED_CONFIG_SCHEMA


def test_config_supported_schema(git_repo_with_commit: Path, write_config) -> None:
    write_config(
        git_repo_with_commit,
        f"[meta]\nschema_version = {SUPPORTED_CONFIG_SCHEMA}\n" + _BASE,
    )
    config = resolve_project_config(git_repo_with_commit)
    assert config.meta.schema_version == SUPPORTED_CONFIG_SCHEMA


def test_config_newer_schema_fails_closed(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        f"[meta]\nschema_version = {SUPPORTED_CONFIG_SCHEMA + 1}\n" + _BASE,
    )
    with pytest.raises(ConfigVersionUnsupportedError):
        resolve_project_config(git_repo_with_commit)


def test_config_invalid_schema_value(git_repo_with_commit: Path, write_config) -> None:
    from ramalio.core.errors import ProjectConfigInvalidError

    write_config(git_repo_with_commit, '[meta]\nschema_version = "one"\n' + _BASE)
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


# --- doctor version checks (R13/AC-09) -------------------------------------


def test_doctor_reports_version_and_schema(
    git_repo_with_commit: Path, write_config, monkeypatch
) -> None:
    write_config(git_repo_with_commit, _BASE)
    monkeypatch.chdir(git_repo_with_commit)
    stdout, stderr = StringIO(), StringIO()
    main(["doctor"], stdout=stdout, stderr=stderr)
    out = stdout.getvalue()
    assert "CLI_VERSION" in out
    assert __version__ in out
    assert "CONFIG_SCHEMA" in out


def test_doctor_newer_schema_is_config_fail(
    git_repo_with_commit: Path, write_config, monkeypatch
) -> None:
    write_config(
        git_repo_with_commit,
        f"[meta]\nschema_version = {SUPPORTED_CONFIG_SCHEMA + 1}\n" + _BASE,
    )
    monkeypatch.chdir(git_repo_with_commit)
    stdout, stderr = StringIO(), StringIO()
    code = main(["doctor"], stdout=stdout, stderr=stderr)
    # An unsupported schema surfaces as a failed config validity check.
    assert code == ExitCode.OPERATION_FAILED
    assert "Global: FAIL" in stdout.getvalue()
