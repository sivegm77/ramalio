from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.core.errors import GitCommandError
from ramalio.git.runner import GitRunner


def test_run_captures_success(git_repo: Path) -> None:
    runner = GitRunner(git_repo)
    output = runner.run("rev-parse", "--is-inside-work-tree")
    assert output.ok
    assert output.returncode == 0
    assert output.stdout.strip() == "true"
    assert output.args == ("rev-parse", "--is-inside-work-tree")


def test_run_captures_failure_without_check(git_repo: Path) -> None:
    runner = GitRunner(git_repo)
    # An unknown ref exits non-zero; without check the caller inspects the code.
    output = runner.run("rev-parse", "--verify", "--quiet", "does-not-exist")
    assert not output.ok
    assert output.returncode != 0


def test_run_with_check_raises_domain_error(git_repo: Path) -> None:
    runner = GitRunner(git_repo)
    with pytest.raises(GitCommandError) as excinfo:
        runner.run("cat-file", "-p", "deadbeef", check=True)
    error = excinfo.value
    assert error.code == "GIT_COMMAND_FAILED"
    assert error.args_run is not None
    assert error.returncode is not None


def test_argv_is_never_shell_interpreted(git_repo: Path) -> None:
    # A token that a shell would treat specially must be passed verbatim as a
    # single argv element (R12): git rejects it as an unknown ref, no shell runs.
    runner = GitRunner(git_repo)
    output = runner.run("rev-parse", "--verify", "--quiet", "; rm -rf /")
    assert not output.ok
