from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ramalio.config.loader import (
    NullPersonalConfig,
    PersonalConfigSource,
    load_project_config,
    resolve_project_config,
)
from ramalio.core.errors import (
    ProjectConfigNotFoundError,
    ProjectConfigParseError,
)
from ramalio.core.project import Project, discover_project

VALID_TOML = """
[project]
name = "demo"
base_branch = "main"
"""


def test_missing_config_raises_not_found(git_repo: Path) -> None:
    # CT-04 — Git repository without config.
    with pytest.raises(ProjectConfigNotFoundError) as excinfo:
        resolve_project_config(git_repo)
    assert excinfo.value.code == "PROJECT_CONFIG_NOT_FOUND"


def test_broken_toml_raises_parse_error(git_repo: Path, write_config) -> None:
    # CT-05 — invalid syntax.
    write_config(git_repo, "[project\nname = ")
    with pytest.raises(ProjectConfigParseError) as excinfo:
        resolve_project_config(git_repo)
    assert excinfo.value.code == "PROJECT_CONFIG_PARSE_ERROR"


def test_resolution_from_root_returns_expected_model(git_repo: Path, write_config) -> None:
    # AC-01 — valid config resolved from the root.
    write_config(git_repo, VALID_TOML)
    resolved = resolve_project_config(git_repo)
    assert resolved.repository_root == git_repo
    assert resolved.project.name == "demo"


def test_resolution_from_subdirectory_matches_root(git_repo: Path, write_config) -> None:
    # AC-02 — same root and effective configuration from a subdirectory.
    write_config(git_repo, VALID_TOML)
    nested = git_repo / "src" / "pkg"
    nested.mkdir(parents=True)

    from_root = resolve_project_config(git_repo)
    from_sub = resolve_project_config(nested)
    assert from_sub == from_root


def test_resolution_is_deterministic(git_repo: Path, write_config) -> None:
    # INV-07 — identical inputs, identical effective configuration.
    write_config(git_repo, VALID_TOML)
    assert resolve_project_config(git_repo) == resolve_project_config(git_repo)


def test_project_toml_overrides_defaults(git_repo: Path, write_config) -> None:
    write_config(
        git_repo,
        '[project]\nname = "demo"\nbase_branch = "develop"\n',
    )
    resolved = resolve_project_config(git_repo)
    assert resolved.project.base_branch == "develop"


def test_environment_override_beats_project_toml(git_repo: Path, write_config) -> None:
    # CT-10 / AC-10 — supported env override applied deterministically.
    write_config(git_repo, VALID_TOML)
    resolved = resolve_project_config(
        git_repo, environ={"RAMALIO_BASE_BRANCH": "release"}
    )
    assert resolved.project.base_branch == "release"


def test_cli_override_beats_environment(git_repo: Path, write_config) -> None:
    # CT-10 / AC-10 — CLI has the highest precedence.
    write_config(git_repo, VALID_TOML)
    resolved = resolve_project_config(
        git_repo,
        environ={"RAMALIO_BASE_BRANCH": "release"},
        cli_overrides={"project": {"base_branch": "hotfix"}},
    )
    assert resolved.project.base_branch == "hotfix"


def test_personal_config_can_override_permitted_field(git_repo: Path, write_config) -> None:
    write_config(git_repo, VALID_TOML)

    class Personal:
        def load(self, project: Project) -> dict:
            return {"worktree": {"directory": ".personal-wt"}}

    resolved = resolve_project_config(git_repo, personal_source=Personal())
    assert resolved.worktree.directory == ".personal-wt"


def test_personal_config_cannot_change_project_identity(git_repo: Path, write_config) -> None:
    # R10 — personal config must not silently redefine the project name.
    write_config(git_repo, VALID_TOML)

    class HijackName:
        def load(self, project: Project) -> dict:
            return {"project": {"name": "not-demo"}}

    resolved = resolve_project_config(git_repo, personal_source=HijackName())
    assert resolved.project.name == "demo"


def test_null_personal_source_satisfies_protocol() -> None:
    # R11 — the personal source interface exists and is optional.
    assert isinstance(NullPersonalConfig(), PersonalConfigSource)


def test_load_project_config_returns_raw_mapping(git_repo: Path, write_config) -> None:
    write_config(git_repo, VALID_TOML)
    project = discover_project(git_repo)
    raw = load_project_config(project)
    assert raw["project"]["name"] == "demo"


# ---- Integration over the three example profiles (CT-13, AC-11, AC-12) ----

PROFILE_EXPECTATIONS = {
    "simple-git": {"base_branch": "main", "has_capabilities": False},
    "web-runtime": {"base_branch": "develop", "has_capabilities": True},
    "cli-python": {"base_branch": "main", "has_capabilities": True},
}


@pytest.mark.parametrize("profile", sorted(PROFILE_EXPECTATIONS))
def test_three_profiles_load_with_same_core(
    profile: str, git_repo: Path, profiles_dir: Path
) -> None:
    source = profiles_dir / f"{profile}.ramalio.toml"
    shutil.copyfile(source, git_repo / ".ramalio.toml")

    resolved = resolve_project_config(git_repo)

    expected = PROFILE_EXPECTATIONS[profile]
    assert resolved.project.name == profile
    assert resolved.project.base_branch == expected["base_branch"]
    assert bool(resolved.capabilities) == expected["has_capabilities"]


def test_web_profile_loads_integration_without_execution(
    git_repo: Path, profiles_dir: Path
) -> None:
    # AC-09 / AC-12 — kiro integration is data; nothing is executed.
    source = profiles_dir / "web-runtime.ramalio.toml"
    shutil.copyfile(source, git_repo / ".ramalio.toml")

    resolved = resolve_project_config(git_repo)
    assert resolved.integrations["kiro"].command == ("kiro-cli", "--v3")
    assert resolved.capabilities["tmux"].enabled is True



# ===========================================================================
# F2 — regression: RAMALIO_RUNTIME_BASE_PROJECT_PATTERN lets a developer's
# personal, non-versioned environment override the shared base runtime
# identity, without the core knowing any project/developer identifier and
# without ever enabling the runtime capability by itself (INV-009).
# ===========================================================================

_RUNTIME_TOML = """
[project]
name = "demo"
base_branch = "main"

[capabilities.runtime]
driver = "docker-compose"
base_project_pattern = "{project}"
"""


def test_f2_runtime_base_project_pattern_env_override_beats_toml(
    git_repo: Path, write_config
) -> None:
    write_config(git_repo, _RUNTIME_TOML)
    resolved = resolve_project_config(
        git_repo,
        environ={"RAMALIO_RUNTIME_BASE_PROJECT_PATTERN": "zurich-edgar"},
    )
    assert (
        resolved.capabilities["runtime"].options["base_project_pattern"]
        == "zurich-edgar"
    )


def test_f2_runtime_base_project_pattern_absent_env_keeps_toml_value(
    git_repo: Path, write_config
) -> None:
    write_config(git_repo, _RUNTIME_TOML)
    resolved = resolve_project_config(git_repo, environ={})
    assert (
        resolved.capabilities["runtime"].options["base_project_pattern"]
        == "{project}"
    )


def test_f2_runtime_base_project_pattern_env_never_enables_runtime_alone(
    git_repo: Path, write_config
) -> None:
    """INV-009: a project that never declared [capabilities.runtime] must not
    have the capability implicitly enabled just because a developer's shell
    profile happens to export this variable."""

    write_config(git_repo, VALID_TOML)  # no [capabilities.*] at all
    resolved = resolve_project_config(
        git_repo,
        environ={"RAMALIO_RUNTIME_BASE_PROJECT_PATTERN": "zurich-edgar"},
    )
    assert "runtime" not in resolved.capabilities


def test_f2_runtime_base_project_pattern_preserves_other_runtime_options(
    git_repo: Path, write_config
) -> None:
    """The override must not clobber sibling options in [capabilities.runtime]
    (e.g. driver, compose_file) — only base_project_pattern changes."""

    write_config(
        git_repo,
        _RUNTIME_TOML + '\ncompose_file = "docker-compose.yml"\n',
    )
    resolved = resolve_project_config(
        git_repo,
        environ={"RAMALIO_RUNTIME_BASE_PROJECT_PATTERN": "zurich-edgar"},
    )
    options = resolved.capabilities["runtime"].options
    assert options["base_project_pattern"] == "zurich-edgar"
    assert options["driver"] == "docker-compose"
    assert options["compose_file"] == "docker-compose.yml"


def test_f2_runtime_base_project_pattern_env_beats_personal_config_too(
    git_repo: Path, write_config
) -> None:
    write_config(git_repo, _RUNTIME_TOML)

    class Personal:
        def load(self, project: Project) -> dict:
            return {"capabilities": {"runtime": {"base_project_pattern": "personal"}}}

    resolved = resolve_project_config(
        git_repo,
        personal_source=Personal(),
        environ={"RAMALIO_RUNTIME_BASE_PROJECT_PATTERN": "zurich-edgar"},
    )
    assert (
        resolved.capabilities["runtime"].options["base_project_pattern"]
        == "zurich-edgar"
    )


def test_f2_sivale_example_config_resolves_developer_scoped_identity(
    tmp_path: Path,
) -> None:
    """End-to-end with the real SiVale example config (E10-S4/F2): the runtime
    base identity that a real harness uses (e.g. zurich-$KIRO_DEVELOPER) can be
    supplied from the developer's own personal environment, never from the
    shared, versioned TOML, and the core never learns any developer name."""

    import os
    import subprocess

    toml = Path("docs/examples/sivale.ramalio.toml").read_text(
        encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c", "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c", "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(tmp_path), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True, capture_output=True,
    )
    (tmp_path / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "seed"], check=True, capture_output=True)
    (tmp_path / ".ramalio.toml").write_text(toml, encoding="utf-8")

    without_override = resolve_project_config(tmp_path)
    assert (
        without_override.capabilities["runtime"].options["base_project_pattern"]
        == "{project}"
    )

    with_override = resolve_project_config(
        tmp_path,
        environ={
            **os.environ,
            "RAMALIO_RUNTIME_BASE_PROJECT_PATTERN": "zurich-edgar",
        },
    )
    assert (
        with_override.capabilities["runtime"].options["base_project_pattern"]
        == "zurich-edgar"
    )
