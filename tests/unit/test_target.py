"""Unit tests for target validation (E1-S1).

Covers CT-01..CT-14 and AC-01..AC-10.  All cases prove the outcome depends only
on the candidate string plus the effective policy: no Git, worktree, history or
external tool is consulted (R9, AC-10).
"""

from __future__ import annotations

import pytest

from ramalio.core.errors import (
    ConfigurationError,
    StateError,
    TargetExampleInvalidError,
    TargetInvalidError,
    TargetRegexInvalidError,
    TargetTooLongError,
)
from ramalio.core.result import ExitCode
from ramalio.core.target import (
    MAX_TARGET_LENGTH,
    Target,
    TargetPolicy,
    TargetValidator,
)

# --- Convention families (R11) -------------------------------------------
# Each family ships its own regex; the core stays agnostic.

FAMILY_A = TargetPolicy(  # Stage/spec
    regex=r"^E[0-9]+-S[0-9]+-[a-z0-9-]+$",
    example="E7-S8-convergencia-schema-tests",
    case_sensitive=True,
)
FAMILY_B = TargetPolicy(  # Feature
    regex=r"^FEATURE-[0-9]+-[a-z0-9-]+$",
    example="FEATURE-123-login",
    case_sensitive=True,
)
FAMILY_C = TargetPolicy(  # Task
    regex=r"^TASK-[0-9]+-[a-z0-9-]+$",
    example="TASK-15-retries",
    case_sensitive=True,
)

ALL_FAMILIES = [FAMILY_A, FAMILY_B, FAMILY_C]


# --- Valid candidates (AC-01) --------------------------------------------


@pytest.mark.parametrize(
    ("policy", "candidate"),
    [
        (FAMILY_A, "E7-S8-convergencia-schema-tests"),  # CT-01
        (FAMILY_B, "FEATURE-123-login"),  # CT-03
        (FAMILY_C, "TASK-15-retries"),  # CT-04
    ],
)
def test_valid_candidate_produces_target(policy: TargetPolicy, candidate: str) -> None:
    validator = TargetValidator(policy)
    target = validator.validate(candidate)
    assert isinstance(target, Target)
    assert target.value == candidate
    assert str(target) == candidate


# --- Invalid candidates against family regex ------------------------------


@pytest.mark.parametrize(
    ("policy", "candidate"),
    [
        (FAMILY_A, "E7-convergencia"),  # CT-02 — misses the -S<n>- part
        (FAMILY_B, "FEATURE-login"),  # missing number
        (FAMILY_C, "TASK-retries"),  # missing number
    ],
)
def test_shape_mismatch_is_rejected(policy: TargetPolicy, candidate: str) -> None:
    validator = TargetValidator(policy)
    with pytest.raises(TargetInvalidError) as excinfo:
        validator.validate(candidate)
    assert excinfo.value.code == "TARGET_INVALID"


# --- Full match, not substring (R3, INV-02, AC-02) ------------------------


@pytest.mark.parametrize("policy", ALL_FAMILIES)
def test_partial_match_with_prefix_or_suffix_is_rejected(policy: TargetPolicy) -> None:
    # CT-05 — an embedded valid value must still be rejected.
    validator = TargetValidator(policy)
    embedded = f"xxx{policy.example}zzz"
    with pytest.raises(TargetInvalidError):
        validator.validate(embedded)


def test_full_match_applies_even_when_regex_omits_anchors() -> None:
    # R3 — the API enforces full-match semantics regardless of anchors.
    policy = TargetPolicy(regex=r"FEATURE-[0-9]+", example="FEATURE-123", case_sensitive=True)
    validator = TargetValidator(policy)
    with pytest.raises(TargetInvalidError):
        validator.validate("xFEATURE-123x")
    assert validator.validate("FEATURE-123").value == "FEATURE-123"


# --- Empty / blank / missing (R4, CT-10, CT-11) ---------------------------


@pytest.mark.parametrize("candidate", ["", "   ", "\t", "\n  \t"])
def test_empty_or_blank_candidate_is_rejected(candidate: str) -> None:
    validator = TargetValidator(FAMILY_A)
    with pytest.raises(TargetInvalidError):
        validator.validate(candidate)


def test_target_value_object_never_empty() -> None:
    with pytest.raises(ValueError):
        Target(value="")
    with pytest.raises(ValueError):
        Target.from_trusted("")


# --- Case sensitivity (R5, AC-05, AC-06, CT-08, CT-09) --------------------


def test_case_sensitive_distinguishes_case() -> None:
    # CT-08 / AC-05 — wrong case fails when case_sensitive = True.
    validator = TargetValidator(FAMILY_B)
    with pytest.raises(TargetInvalidError):
        validator.validate("feature-123-login")


def test_case_insensitive_allows_alternative_case_without_rewriting() -> None:
    # CT-09 / AC-06 — insensitive matching accepts alternative case and the
    # original string is preserved verbatim (no rewrite in this spec).
    policy = TargetPolicy(
        regex=r"^FEATURE-[0-9]+-[a-z0-9-]+$",
        example="FEATURE-123-login",
        case_sensitive=False,
    )
    validator = TargetValidator(policy)
    target = validator.validate("feature-123-LOGIN")
    assert target.value == "feature-123-LOGIN"  # unchanged


# --- Length limit (R12, AC-08, CT-12, CT-13) ------------------------------


def test_boundary_length_is_allowed_when_regex_matches() -> None:
    # CT-12 — exactly MAX_TARGET_LENGTH characters and matching the regex.
    slug = "a" * (MAX_TARGET_LENGTH - len("FEATURE-1-"))
    candidate = f"FEATURE-1-{slug}"
    assert len(candidate) == MAX_TARGET_LENGTH
    validator = TargetValidator(FAMILY_B)
    assert validator.validate(candidate).value == candidate


def test_over_limit_is_rejected_as_too_long() -> None:
    # CT-13 — 201 characters -> TARGET_TOO_LONG, checked before regex.
    candidate = "a" * (MAX_TARGET_LENGTH + 1)
    validator = TargetValidator(FAMILY_B)
    with pytest.raises(TargetTooLongError) as excinfo:
        validator.validate(candidate)
    assert excinfo.value.code == "TARGET_TOO_LONG"


# --- Diagnostic message (R8, AC-07) ---------------------------------------


def test_invalid_message_includes_value_and_example() -> None:
    validator = TargetValidator(FAMILY_B)
    with pytest.raises(TargetInvalidError) as excinfo:
        validator.validate("feature 123 login")
    message = str(excinfo.value)
    assert "feature 123 login" in message  # received value
    assert FAMILY_B.example in message  # configured example


# --- Regex configuration validation (R2, AC-03, CT-06) --------------------


def test_uncompilable_regex_is_rejected() -> None:
    # CT-06 — broken pattern -> TARGET_REGEX_INVALID at construction time.
    policy = TargetPolicy(regex=r"^[A-Z", example="A", case_sensitive=True)
    with pytest.raises(TargetRegexInvalidError) as excinfo:
        TargetValidator(policy)
    assert excinfo.value.code == "TARGET_REGEX_INVALID"


def test_empty_regex_is_rejected() -> None:
    policy = TargetPolicy(regex="", example="A", case_sensitive=True)
    with pytest.raises(TargetRegexInvalidError):
        TargetValidator(policy)


# --- Example validation (R6, AC-04, CT-07) --------------------------------


def test_example_not_matching_regex_is_rejected() -> None:
    # CT-07 — example incompatible with the policy -> TARGET_EXAMPLE_INVALID.
    policy = TargetPolicy(
        regex=r"^FEATURE-[0-9]+$", example="not-a-feature", case_sensitive=True
    )
    with pytest.raises(TargetExampleInvalidError) as excinfo:
        TargetValidator(policy)
    assert excinfo.value.code == "TARGET_EXAMPLE_INVALID"


def test_empty_example_is_rejected() -> None:
    policy = TargetPolicy(regex=r"^A$", example="", case_sensitive=True)
    with pytest.raises(TargetExampleInvalidError):
        TargetValidator(policy)


# --- Reuse across conventions (R10, AC-09) --------------------------------


def test_same_validator_class_serves_multiple_conventions() -> None:
    # AC-09 — three projects with different regex share one implementation.
    validators = {
        "A": TargetValidator(FAMILY_A),
        "B": TargetValidator(FAMILY_B),
        "C": TargetValidator(FAMILY_C),
    }
    assert all(isinstance(v, TargetValidator) for v in validators.values())
    assert validators["A"].validate("E1-S1-target").value == "E1-S1-target"
    assert validators["B"].validate("FEATURE-9-x").value == "FEATURE-9-x"
    assert validators["C"].validate("TASK-9-x").value == "TASK-9-x"
    # A candidate valid for one family is rejected by the others.
    with pytest.raises(TargetInvalidError):
        validators["B"].validate("TASK-9-x")


# --- No inference (R9, AC-10, CT-14) --------------------------------------


def test_validation_is_pure_function_of_candidate_and_policy() -> None:
    # CT-14 / AC-10 — a partial target fails even if a similar branch existed.
    # The validator has no access to Git/state; determinism across repeated
    # calls demonstrates the outcome depends only on (candidate, policy).
    validator = TargetValidator(FAMILY_B)
    partial = "FEATURE-123"  # missing the slug part
    for _ in range(3):
        with pytest.raises(TargetInvalidError):
            validator.validate(partial)
    # The full, valid candidate is accepted every time.
    for _ in range(3):
        assert validator.validate("FEATURE-123-login").value == "FEATURE-123-login"


# --- Error taxonomy / exit codes ------------------------------------------


def test_domain_errors_have_stable_codes_and_exit_codes() -> None:
    assert TargetInvalidError("x").exit_code == ExitCode.STATE_ERROR
    assert TargetTooLongError("x").exit_code == ExitCode.STATE_ERROR
    assert TargetRegexInvalidError("x").exit_code == ExitCode.CONFIGURATION_ERROR
    assert TargetExampleInvalidError("x").exit_code == ExitCode.CONFIGURATION_ERROR
    # Config-time failures are configuration errors; candidate failures are
    # state errors.
    assert isinstance(TargetRegexInvalidError("x"), ConfigurationError)
    assert isinstance(TargetInvalidError("x"), StateError)
