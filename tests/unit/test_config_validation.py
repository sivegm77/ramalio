from __future__ import annotations

from pathlib import Path

import pytest

from ramalio.config.defaults import product_defaults
from ramalio.config.models import ResolvedProjectConfig
from ramalio.config.validation import build_resolved_config
from ramalio.core.errors import ProjectConfigInvalidError

ROOT = Path("/tmp/repo")


def _merge(overrides: dict) -> dict:
    """Merge ``overrides`` on top of product defaults for validation tests."""

    merged = product_defaults()
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _valid() -> dict:
    return _merge({"project": {"name": "demo", "base_branch": "main"}})


def test_valid_configuration_builds_resolved_model() -> None:
    resolved = build_resolved_config(_valid(), repository_root=ROOT)
    assert isinstance(resolved, ResolvedProjectConfig)
    assert resolved.repository_root == ROOT
    assert resolved.project.name == "demo"
    assert resolved.project.base_branch == "main"


def test_defaults_are_observable_when_optional_fields_omitted() -> None:
    # CT-09 — omitting optional fields falls back to universal defaults.
    resolved = build_resolved_config(_valid(), repository_root=ROOT)
    assert resolved.worktree.directory == ".local-wt"
    assert resolved.worktree.pattern == "{target}"
    assert resolved.branch.pattern == "{target}"
    assert resolved.target.case_sensitive is False
    assert resolved.target.normalization.replace_spaces == "-"


def test_empty_required_field_is_invalid() -> None:
    # CT-06 — project.name = "".
    with pytest.raises(ProjectConfigInvalidError) as excinfo:
        build_resolved_config(
            _merge({"project": {"name": "", "base_branch": "main"}}),
            repository_root=ROOT,
        )
    assert excinfo.value.code == "PROJECT_CONFIG_INVALID"
    assert "project.name" in str(excinfo.value)


def test_wrong_scalar_type_is_invalid() -> None:
    # CT-07 — project.base_branch = [].
    with pytest.raises(ProjectConfigInvalidError) as excinfo:
        build_resolved_config(
            _merge({"project": {"name": "demo", "base_branch": []}}),
            repository_root=ROOT,
        )
    assert "project.base_branch" in str(excinfo.value)


def test_boolean_is_not_accepted_as_string() -> None:
    with pytest.raises(ProjectConfigInvalidError):
        build_resolved_config(
            _merge({"project": {"name": "demo", "base_branch": True}}),
            repository_root=ROOT,
        )


def test_unknown_key_in_known_section_is_rejected() -> None:
    # CT-08 — worktree.direcotry (typo) must fail-closed.
    merged = _valid()
    merged["worktree"] = {**merged["worktree"], "direcotry": ".local-wt"}
    with pytest.raises(ProjectConfigInvalidError) as excinfo:
        build_resolved_config(merged, repository_root=ROOT)
    assert "direcotry" in str(excinfo.value)


def test_unknown_top_level_section_is_rejected() -> None:
    merged = _valid()
    merged["unknown_section"] = {"foo": "bar"}
    with pytest.raises(ProjectConfigInvalidError) as excinfo:
        build_resolved_config(merged, repository_root=ROOT)
    assert "unknown_section" in str(excinfo.value)


def test_table_where_scalar_expected_is_invalid() -> None:
    with pytest.raises(ProjectConfigInvalidError):
        build_resolved_config(
            _merge({"project": {"name": {"nested": "table"}, "base_branch": "main"}}),
            repository_root=ROOT,
        )


def test_capability_is_loaded_but_not_executed() -> None:
    # CT-11 / AC-08 — capabilities.tmux.enabled = true.
    merged = _valid()
    merged["capabilities"] = {"tmux": {"enabled": True}}
    resolved = build_resolved_config(merged, repository_root=ROOT)
    assert resolved.capabilities["tmux"].enabled is True
    assert resolved.capabilities["tmux"].name == "tmux"


def test_integration_is_loaded_but_not_executed() -> None:
    # CT-12 / AC-09 — integrations.kiro.command loaded as structured argv only.
    merged = _valid()
    merged["integrations"] = {
        "kiro": {"enabled": True, "command": ["kiro-cli", "--v3"]}
    }
    resolved = build_resolved_config(merged, repository_root=ROOT)
    assert resolved.integrations["kiro"].command == ("kiro-cli", "--v3")
    assert resolved.integrations["kiro"].enabled is True
