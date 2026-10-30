"""Integration tests for the config -> target-validator bridge (E1-S1 T7).

These tests prove the validator consumes :class:`ResolvedProjectConfig` (E1-S0)
and that three fixture profiles with different regex share the same
implementation (R10, AC-09) without any project regex hardcoded in the core.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from ramalio.config.defaults import product_defaults
from ramalio.config.target import build_target_policy, build_target_validator
from ramalio.config.validation import build_resolved_config
from ramalio.core.errors import TargetExampleInvalidError, TargetInvalidError, TargetRegexInvalidError
from ramalio.core.target import TargetValidator

ROOT = Path("/tmp/repo")


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolved_from_profile(profiles_dir: Path, name: str):
    raw = tomllib.loads((profiles_dir / f"{name}.ramalio.toml").read_text("utf-8"))
    merged = _deep_merge(product_defaults(), raw)
    return build_resolved_config(merged, repository_root=ROOT)


def _resolved(overrides: dict):
    base = {"project": {"name": "demo", "base_branch": "main"}}
    merged = _deep_merge(product_defaults(), _deep_merge(base, overrides))
    return build_resolved_config(merged, repository_root=ROOT)


# --- The validator consumes ResolvedProjectConfig (T7) --------------------


@pytest.mark.parametrize(
    ("profile", "valid", "invalid"),
    [
        ("cli-python", "PROJ-123", "proj-123"),
        # simple-git is case-insensitive, so an invalid value must break the
        # character class itself (space is not in [a-z0-9-]).
        ("simple-git", "my-feature", "my feature"),
        ("web-runtime", "feature/login-form", "feature login form"),
    ],
)
def test_validator_from_profile(profiles_dir: Path, profile: str, valid: str, invalid: str) -> None:
    config = _resolved_from_profile(profiles_dir, profile)
    validator = build_target_validator(config)
    assert isinstance(validator, TargetValidator)
    assert validator.validate(valid).value == valid
    with pytest.raises(TargetInvalidError):
        validator.validate(invalid)


def test_three_profiles_share_the_same_validator_class(profiles_dir: Path) -> None:
    # AC-09 — one implementation, three conventions.
    validators = [
        build_target_validator(_resolved_from_profile(profiles_dir, name))
        for name in ("cli-python", "simple-git", "web-runtime")
    ]
    assert all(isinstance(v, TargetValidator) for v in validators)
    assert {type(v) for v in validators} == {TargetValidator}


# --- Policy extraction and missing configuration --------------------------


def test_build_policy_reads_resolved_values(profiles_dir: Path) -> None:
    config = _resolved_from_profile(profiles_dir, "cli-python")
    policy = build_target_policy(config)
    assert policy.regex == "^[A-Z]+-[0-9]+$"
    assert policy.example == "PROJ-123"
    assert policy.case_sensitive is True


def test_missing_regex_raises_regex_invalid() -> None:
    # target.regex omitted -> required for validation (R1).
    config = _resolved({"target": {"example": "X"}})
    with pytest.raises(TargetRegexInvalidError):
        build_target_validator(config)


def test_missing_example_raises_example_invalid() -> None:
    config = _resolved({"target": {"regex": "^X$"}})
    with pytest.raises(TargetExampleInvalidError):
        build_target_validator(config)
