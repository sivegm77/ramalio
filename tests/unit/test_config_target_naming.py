"""Integration tests for the config->normalizer->naming builders (E1-S2).

These prove the resolved configuration wires the E1-S2 core services correctly
and that a single implementation serves three different project conventions
(R19, AC-12) end to end, starting from resolved configuration.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from ramalio.config.defaults import product_defaults
from ramalio.config.target import (
    build_target_normalizer,
    build_workspace_naming,
)
from ramalio.config.validation import build_resolved_config
from ramalio.core.target import TargetNormalizer

ROOT = Path("/tmp/repo")


def _resolved(overrides: dict):
    """Merge ``overrides`` on top of defaults and build a resolved config."""

    merged = product_defaults()

    def deep(base: dict, extra: dict) -> dict:
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = deep(dict(base[key]), value)
            else:
                base[key] = value
        return base

    merged = deep(merged, overrides)
    return build_resolved_config(merged, repository_root=ROOT)


# The three project conventions from R19, each with its own config.
SPEC_CFG = _resolved(
    {
        "project": {"name": "sivale", "base_branch": "main"},
        "target": {
            "regex": r"^E[0-9]+-S[0-9]+-[a-z0-9-]+$",
            "example": "E7-S8-convergencia-schema-tests",
            "case_sensitive": True,
            "normalization": {
                "trim": True,
                "lowercase_slug": True,
                "replace_spaces": "-",
                "collapse_dashes": True,
                "slug_separator": "-",
                "preserve_prefix_segments": 2,
            },
        },
        "branch": {"pattern": "spec/{target}"},
        "worktree": {"directory": ".local-wt", "pattern": "{target}"},
    }
)
FEATURE_CFG = _resolved(
    {
        "project": {"name": "feat", "base_branch": "main"},
        "target": {
            "regex": r"^FEATURE-[0-9]+-[a-z0-9-]+$",
            "example": "FEATURE-123-login",
            "case_sensitive": True,
            "normalization": {"preserve_prefix_segments": 2},
        },
        "branch": {"pattern": "spec/{target}"},
        "worktree": {"directory": ".worktrees", "pattern": "wt-{target}"},
    }
)
TASK_CFG = _resolved(
    {
        "project": {"name": "task", "base_branch": "main"},
        "target": {
            "regex": r"^TASK-[0-9]+-[a-z0-9-]+$",
            "example": "TASK-15-retries",
            "case_sensitive": True,
            "normalization": {"preserve_prefix_segments": 2},
        },
        "branch": {"pattern": "task/{target}"},
        "worktree": {"directory": ".local-wt", "pattern": "{target}"},
    }
)


def test_builder_returns_normalizer_bound_to_validator() -> None:
    normalizer = build_target_normalizer(SPEC_CFG)
    assert isinstance(normalizer, TargetNormalizer)
    result = normalizer.normalize("E7-S8-Convergencia Schema Tests")
    assert result.normalized_value == "E7-S8-convergencia-schema-tests"
    assert result.changed is True


@pytest.mark.parametrize(
    ("cfg", "raw", "canonical", "branch", "worktree"),
    [
        (
            SPEC_CFG,
            "  E7-S8-Convergencia Schema Tests  ",
            "E7-S8-convergencia-schema-tests",
            "spec/E7-S8-convergencia-schema-tests",
            ".local-wt/E7-S8-convergencia-schema-tests",
        ),
        (
            FEATURE_CFG,
            "FEATURE-123-Login",
            "FEATURE-123-login",
            "spec/FEATURE-123-login",
            ".worktrees/wt-FEATURE-123-login",
        ),
        (
            TASK_CFG,
            "TASK-15-Retries",
            "TASK-15-retries",
            "task/TASK-15-retries",
            ".local-wt/TASK-15-retries",
        ),
    ],
)
def test_end_to_end_three_conventions(
    cfg, raw: str, canonical: str, branch: str, worktree: str
) -> None:
    # raw -> canonical target -> branch -> worktree path, no mutations.
    normalizer = build_target_normalizer(cfg)
    naming = build_workspace_naming(cfg)

    result = normalizer.normalize(raw)
    assert result.normalized_value == canonical

    identity = naming.resolve(result.target)
    assert identity.branch_name == branch
    assert identity.worktree_path == PurePosixPath(worktree)
