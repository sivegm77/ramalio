"""Integration environment policy (E5-S1 / E7-S2 R13 / E9-S3 R4-R8).

By default an integration inherits only the controlled base environment, so
unrelated host variables never leak into the launched tool.  A tool that needs
host variables (e.g. AWS_PROFILE) must opt in explicitly via ``pass_env``
(an allowlist of variable *names*) in its ``[integrations.<name>]`` section.
Secret *values* never live in the TOML — only variable *names* (E9-S3 INV-06).

``inherit_env`` is not part of the public contract (E9-S3 R8/INV-05): a config
that declares it is rejected as an unsupported key.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import ProjectConfigInvalidError
from ramalio.integrations import BaseIntegration, IntegrationContext


class _Tool(BaseIntegration):
    integration_name = "toolx"


def _config(integrations: str) -> str:
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
def captured_env(monkeypatch):
    """Capture the merged env a launched integration would receive.

    Patches ``SafeProcessRunner.popen`` (not the global subprocess) so unrelated
    subprocess use (e.g. Git discovery) is unaffected, and records the exact
    environment the runner would hand to the child via its own env-merge logic.
    """

    from ramalio.security.process import SafeProcessRunner

    captured: dict[str, dict[str, str]] = {}

    class _FakeProc:
        pid = 4242

    real_merged = SafeProcessRunner._merged_env

    def fake_popen(self, spec, **kwargs):
        captured["env"] = real_merged(self, spec.env)
        return _FakeProc()

    monkeypatch.setattr(SafeProcessRunner, "popen", fake_popen)
    return captured


def _ctx(project: Path) -> IntegrationContext:
    cfg = resolve_project_config(project)
    return IntegrationContext(
        config=cfg, target="feat-a", worktree_path=project
    )


def test_default_does_not_inherit_unrelated_host_var(
    git_repo_with_commit: Path, write_config, captured_env, monkeypatch
) -> None:
    monkeypatch.setenv("SECRET_HOST_ONLY", "leak-me")
    write_config(
        git_repo_with_commit,
        _config('\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'),
    )
    _Tool().open(_ctx(git_repo_with_commit))
    # Default policy: the unrelated host variable is NOT forwarded (INV-03).
    assert "SECRET_HOST_ONLY" not in captured_env["env"]


def test_pass_env_forwards_allowlisted_var(
    git_repo_with_commit: Path, write_config, captured_env, monkeypatch
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "sivale")
    monkeypatch.setenv("SECRET_HOST_ONLY", "leak-me")
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["AWS_PROFILE"]\n'
        ),
    )
    _Tool().open(_ctx(git_repo_with_commit))
    env = captured_env["env"]
    # Explicitly allowlisted variable is forwarded; others still are not (INV-04).
    assert env.get("AWS_PROFILE") == "sivale"
    assert "SECRET_HOST_ONLY" not in env


def test_pass_env_absent_variable_is_not_forwarded(
    git_repo_with_commit: Path, write_config, captured_env, monkeypatch
) -> None:
    """A name declared in ``pass_env`` but absent from the environment is simply
    not forwarded; the core invents no value (E9-S3 R7)."""

    monkeypatch.delenv("MISSING_VAR", raising=False)
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["MISSING_VAR"]\n'
        ),
    )
    _Tool().open(_ctx(git_repo_with_commit))
    assert "MISSING_VAR" not in captured_env["env"]


# --- fail-closed public contract (E9-S3 R8/R6/INV-05) ----------------------


def test_inherit_env_is_rejected_as_unsupported_key(
    git_repo_with_commit: Path, write_config
) -> None:
    """``inherit_env`` is no longer part of the public contract; it must be
    rejected as an unsupported key at config load (E9-S3 R8/AC-06/INV-05)."""

    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            "inherit_env = true\n"
        ),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_pass_env_non_list_is_rejected(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = "AWS_PROFILE"\n'
        ),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_pass_env_with_invalid_entries_is_rejected(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["", 123]\n'
        ),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_pass_env_inline_assignment_is_rejected(
    git_repo_with_commit: Path, write_config
) -> None:
    """``pass_env`` holds variable names, not inline ``KEY=value`` (E9-S3 R6)."""

    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["AWS_PROFILE=prod"]\n'
        ),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_valid_env_policy_still_passes_validation(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["AWS_PROFILE"]\n'
        ),
    )
    _Tool().validate_config(_ctx(git_repo_with_commit))  # must not raise


def test_pass_env_accepts_non_shell_identifier_name(
    git_repo_with_commit: Path, write_config
) -> None:
    """E9-S3 R6: ``pass_env`` must not impose a shell-identifier convention.

    A name valid for ``os.environ`` but not a C-style identifier (e.g. one with
    a dash) must be accepted, not rejected (H2 regression)."""

    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["MY-VAR", "lower.case", "AWS_PROFILE"]\n'
        ),
    )
    cfg = resolve_project_config(git_repo_with_commit)
    assert cfg.integrations["toolx"].pass_env == ("MY-VAR", "lower.case", "AWS_PROFILE")


def test_pass_env_secret_value_not_leaked_in_diagnostics(
    git_repo_with_commit: Path, write_config, monkeypatch
) -> None:
    """A secret-looking value forwarded via ``pass_env`` must not appear in
    redacted diagnostics (E9-S3 R10/AC-05)."""

    from ramalio.security.process import redact_environment

    monkeypatch.setenv("APP_SECRET_TOKEN", "super-secret-value")
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.toolx]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["APP_SECRET_TOKEN"]\n'
        ),
    )
    extra = _Tool()._env_policy(_ctx(git_repo_with_commit))
    assert extra.get("APP_SECRET_TOKEN") == "super-secret-value"
    # Diagnostics never expose the raw secret value.
    redacted = redact_environment(extra)
    assert redacted["APP_SECRET_TOKEN"] == "***"
    assert "super-secret-value" not in redacted.values()



def test_doctor_cli_does_not_leak_pass_env_secret(
    git_repo_with_commit: Path, write_config, monkeypatch
) -> None:
    """E9-S3 minimal test case #12 (R10/AC-05), end-to-end.

    A secret-looking variable present in the environment and allowlisted via a
    real integration's ``pass_env`` must never appear in the ``doctor`` output
    (neither stdout nor stderr). ``doctor`` is exercised through the real CLI
    entry point, not by inspecting a helper in isolation.
    """

    from io import StringIO

    from ramalio.cli import main

    secret = "super-secret-value-do-not-leak"
    monkeypatch.setenv("APP_SECRET_TOKEN", secret)
    # Use the real 'kiro' integration (present in the default registry) so the
    # doctor integration checks actually run. 'sleep' is a widely-available
    # stand-in executable so availability resolves deterministically.
    write_config(
        git_repo_with_commit,
        _config(
            '\n[integrations.kiro]\nenabled = true\ncommand = ["sleep"]\n'
            'pass_env = ["APP_SECRET_TOKEN"]\n'
        ),
    )
    monkeypatch.chdir(git_repo_with_commit)
    stdout, stderr = StringIO(), StringIO()
    main(["doctor"], stdout=stdout, stderr=stderr)

    out, err = stdout.getvalue(), stderr.getvalue()
    # The integration was evaluated (doctor ran its checks)...
    assert "INTEGRATION_KIRO" in out
    # ...but the secret value never surfaces in any diagnostic stream (R10).
    assert secret not in out
    assert secret not in err
