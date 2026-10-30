"""Unit tests for target normalization (E1-S2).

Covers CT-01..CT-09 and AC-01..AC-07, AC-12, AC-14.  Every case proves the
pipeline is deterministic, idempotent, opt-in per rule and that the normalized
value is only a :class:`Target` after E1-S1 validates it (INV-03, R9).
"""

from __future__ import annotations

import pytest

from ramalio.core.errors import (
    TargetInvalidError,
    TargetNormalizationEmptyError,
    TargetNormalizationFailedError,
)
from ramalio.core.target import (
    NormalizationRules,
    Target,
    TargetNormalizer,
    TargetPolicy,
    TargetValidator,
)

# --- Convention families (R19) -------------------------------------------

FAMILY_SPEC = TargetPolicy(  # SiVale-like: E<n>-S<n>-slug
    regex=r"^E[0-9]+-S[0-9]+-[a-z0-9-]+$",
    example="E7-S8-convergencia-schema-tests",
    case_sensitive=True,
)
FAMILY_FEATURE = TargetPolicy(
    regex=r"^FEATURE-[0-9]+-[a-z0-9-]+$",
    example="FEATURE-123-login",
    case_sensitive=True,
)
FAMILY_TASK = TargetPolicy(
    regex=r"^TASK-[0-9]+-[a-z0-9-]+$",
    example="TASK-15-retries",
    case_sensitive=True,
)


def _rules(
    *,
    trim: bool = False,
    replace_spaces: str = "",
    collapse_dashes: bool = False,
    lowercase_slug: bool = False,
    slug_separator: str = "-",
    preserve_prefix_segments: int = 0,
) -> NormalizationRules:
    return NormalizationRules(
        trim=trim,
        replace_spaces=replace_spaces,
        collapse_dashes=collapse_dashes,
        lowercase_slug=lowercase_slug,
        slug_separator=slug_separator,
        preserve_prefix_segments=preserve_prefix_segments,
    )


def _normalizer(policy: TargetPolicy, rules: NormalizationRules) -> TargetNormalizer:
    return TargetNormalizer(rules, TargetValidator(policy))


# --- CT-01 canonical no-op / AC-01 ----------------------------------------


def test_canonical_value_is_unchanged() -> None:
    norm = _normalizer(
        FAMILY_SPEC,
        _rules(trim=True, replace_spaces="-", collapse_dashes=True,
               lowercase_slug=True, preserve_prefix_segments=2),
    )
    result = norm.normalize("E7-S8-convergencia-schema-tests")
    assert result.normalized_value == "E7-S8-convergencia-schema-tests"
    assert result.changed is False
    assert isinstance(result.target, Target)


# --- CT-02 trim / AC-02 ---------------------------------------------------


def test_trim_only_when_enabled() -> None:
    raw = "  FEATURE-123-login  "
    enabled = _normalizer(FAMILY_FEATURE, _rules(trim=True))
    result = enabled.normalize(raw)
    assert result.normalized_value == "FEATURE-123-login"
    assert result.changed is True


def test_trim_disabled_keeps_value_and_regex_rejects() -> None:
    disabled = _normalizer(FAMILY_FEATURE, _rules(trim=False))
    with pytest.raises(TargetInvalidError):
        disabled.normalize("  FEATURE-123-login  ")


# --- CT-03 replace spaces / AC-03 -----------------------------------------


def test_replace_spaces_converts_internal_whitespace() -> None:
    norm = _normalizer(
        FAMILY_FEATURE,
        _rules(trim=True, replace_spaces="-", lowercase_slug=True,
               preserve_prefix_segments=2),
    )
    result = norm.normalize("FEATURE-123-login page")
    assert result.normalized_value == "FEATURE-123-login-page"
    assert result.changed is True


def test_replace_spaces_disabled_leaves_spaces() -> None:
    norm = _normalizer(FAMILY_FEATURE, _rules(trim=True, replace_spaces=""))
    with pytest.raises(TargetInvalidError):
        norm.normalize("FEATURE-123-login page")


# --- CT-04 collapse dashes / AC-04 ----------------------------------------


def test_collapse_repeated_dashes() -> None:
    norm = _normalizer(FAMILY_FEATURE, _rules(collapse_dashes=True))
    result = norm.normalize("FEATURE-123---login")
    assert result.normalized_value == "FEATURE-123-login"
    assert result.changed is True


# --- CT-05/06/07 lowercase slug preserving prefix / AC-05 -----------------


@pytest.mark.parametrize(
    ("policy", "preserve", "raw", "expected"),
    [
        (FAMILY_SPEC, 2, "E7-S8-Convergencia-Schema-Tests",
         "E7-S8-convergencia-schema-tests"),  # CT-05
        (FAMILY_FEATURE, 2, "FEATURE-123-Login-Page",
         "FEATURE-123-login-page"),  # CT-06
        (FAMILY_TASK, 2, "TASK-15-Retries", "TASK-15-retries"),  # CT-07
    ],
)
def test_lowercase_slug_preserves_configured_prefix(
    policy: TargetPolicy, preserve: int, raw: str, expected: str
) -> None:
    norm = _normalizer(
        policy, _rules(lowercase_slug=True, slug_separator="-",
                       preserve_prefix_segments=preserve)
    )
    result = norm.normalize(raw)
    assert result.normalized_value == expected
    assert result.target.value == expected


def test_lowercase_slug_requires_separator() -> None:
    # Degenerate config: empty separator with lowercase_slug -> fail (R7).
    norm = _normalizer(
        FAMILY_FEATURE, _rules(lowercase_slug=True, slug_separator="")
    )
    with pytest.raises(TargetNormalizationFailedError) as excinfo:
        norm.normalize("FEATURE-123-Login")
    assert excinfo.value.code == "TARGET_NORMALIZATION_FAILED"


# --- CT-08 normalization produces invalid / AC-06, AC-07 ------------------


def test_normalization_producing_invalid_is_rejected_by_e1s1() -> None:
    # Transformable syntactically but the final regex still fails (R9).
    norm = _normalizer(FAMILY_FEATURE, _rules(trim=True, replace_spaces="-"))
    with pytest.raises(TargetInvalidError) as excinfo:
        norm.normalize("  FEATURE login  ")  # -> "FEATURE-login", no number
    assert excinfo.value.code == "TARGET_INVALID"


# --- R8 empty result ------------------------------------------------------


def test_empty_normalization_result_fails_before_target() -> None:
    norm = _normalizer(FAMILY_FEATURE, _rules(trim=True))
    with pytest.raises(TargetNormalizationEmptyError) as excinfo:
        norm.normalize("     ")
    assert excinfo.value.code == "TARGET_NORMALIZATION_EMPTY"


# --- CT-09 idempotence / AC-14 --------------------------------------------


@pytest.mark.parametrize(
    ("policy", "preserve", "raw"),
    [
        (FAMILY_SPEC, 2, "  E7-S8-Convergencia  Schema---Tests  "),
        (FAMILY_FEATURE, 2, "FEATURE-123-Login   Page"),
        (FAMILY_TASK, 2, "  TASK-15-Retries  "),
    ],
)
def test_normalization_is_idempotent(
    policy: TargetPolicy, preserve: int, raw: str
) -> None:
    norm = _normalizer(
        policy,
        _rules(trim=True, replace_spaces="-", collapse_dashes=True,
               lowercase_slug=True, preserve_prefix_segments=preserve),
    )
    once = norm.normalize(raw).normalized_value
    twice = norm.normalize(once).normalized_value
    assert once == twice
    # A second normalization of an already-canonical value reports no change.
    assert norm.normalize(once).changed is False


# --- AC-12 same implementation, three conventions -------------------------


def test_same_normalizer_class_serves_three_conventions() -> None:
    cases = [
        (FAMILY_SPEC, 2, "E7-S8-Convergencia Schema Tests",
         "E7-S8-convergencia-schema-tests"),
        (FAMILY_FEATURE, 2, "FEATURE-123-Login", "FEATURE-123-login"),
        (FAMILY_TASK, 2, "TASK-15-Retries", "TASK-15-retries"),
    ]
    for policy, preserve, raw, expected in cases:
        norm = _normalizer(
            policy,
            _rules(trim=True, replace_spaces="-", collapse_dashes=True,
                   lowercase_slug=True, preserve_prefix_segments=preserve),
        )
        assert norm.normalize(raw).target.value == expected
