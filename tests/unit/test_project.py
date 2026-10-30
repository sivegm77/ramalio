from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.core.errors import NotInGitRepositoryError
from ramalio.core.project import (
    PROJECT_CONFIG_FILENAME,
    discover_project,
    discover_repository_root,
)


def test_discover_from_root_returns_repository_root(git_repo: Path) -> None:
    # CT-01 — repository valid, cwd = root.
    assert discover_repository_root(git_repo) == git_repo


def test_discover_from_subdirectory_returns_same_root(git_repo: Path) -> None:
    # CT-02 — repository valid, cwd = src/foo/bar.
    nested = git_repo / "src" / "foo" / "bar"
    nested.mkdir(parents=True)
    assert discover_repository_root(nested) == git_repo


def test_discover_outside_git_raises_stable_error(tmp_path: Path) -> None:
    # CT-03 — temporary directory without .git.
    with pytest.raises(NotInGitRepositoryError) as excinfo:
        discover_repository_root(tmp_path)
    assert excinfo.value.code == "NOT_IN_GIT_REPOSITORY"


def test_discover_project_exposes_config_path(git_repo: Path) -> None:
    project = discover_project(git_repo)
    assert project.repository_root == git_repo
    assert project.config_path == git_repo / PROJECT_CONFIG_FILENAME


def test_discover_defaults_to_cwd(git_repo: Path, monkeypatch) -> None:
    monkeypatch.chdir(git_repo)
    assert discover_repository_root() == git_repo
