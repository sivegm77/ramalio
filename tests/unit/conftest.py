from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a real, empty Git repository in a temporary directory.

    ``git init`` is enough for ``rev-parse --show-toplevel`` to resolve the
    root; no commits or user identity are required.
    """

    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp_path.resolve()


def _run_git(cwd: Path, *args: str) -> str:
    """Run a Git command in ``cwd`` for test setup and return stdout.

    Test fixtures are allowed to mutate Git (that is how they build real
    repositories); the product code under test never does (INV-03).
    """

    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


@pytest.fixture
def git_env(monkeypatch) -> None:
    """Provide a deterministic Git identity so commits succeed in CI."""

    monkeypatch.setenv("GIT_AUTHOR_NAME", "ramalio-test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "ramalio-test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


@pytest.fixture
def run_git():
    """Expose the raw Git helper to tests that build custom repository shapes."""

    return _run_git


@pytest.fixture
def git_repo_with_commit(git_repo: Path, git_env: None) -> Path:
    """A real repository with a single commit on branch ``main`` (CT-01).

    ``git worktree add`` and branch listing require at least one commit, so this
    fixture is the baseline for the E2-S0 integration tests.
    """

    _run_git(git_repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (git_repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(git_repo, "add", "README.md")
    _run_git(git_repo, "commit", "-q", "-m", "seed")
    return git_repo


@pytest.fixture
def profiles_dir() -> Path:
    """Return the directory holding the three example project profiles."""

    return Path(__file__).resolve().parents[1] / "fixtures" / "profiles"


def _write_config(root: Path, body: str) -> Path:
    """Write ``.ramalio.toml`` at ``root`` and return its path."""

    config_path = root / ".ramalio.toml"
    config_path.write_text(body, encoding="utf-8")
    return config_path


@pytest.fixture
def write_config():
    """Return a helper that writes ``.ramalio.toml`` at a given root."""

    return _write_config
