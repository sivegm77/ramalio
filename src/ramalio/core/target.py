"""Target domain model and configurable validator (E1-S1).

This module answers a single question deterministically::

    Does this candidate belong to the convention declared by this project?

It never infers a target from Git, worktrees, history, partial slugs or
conversational context (INV-03, R9): the outcome depends solely on the
candidate string and the effective :class:`TargetPolicy`.

Normalization (trimming, lowercasing the slug, collapsing dashes, ...) is now
implemented here too (E1-S2) via :class:`TargetNormalizer`, which produces a
:class:`TargetNormalizationResult` and always ends by validating through
:class:`TargetValidator` (INV-03).  Validation itself never rewrites the value
it receives (E1-S1 INV-06, R6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .errors import (
    TargetExampleInvalidError,
    TargetInvalidError,
    TargetNormalizationEmptyError,
    TargetNormalizationFailedError,
    TargetRegexInvalidError,
    TargetTooLongError,
)

# Product-level upper bound (R12).  Wide enough for real work-unit names, small
# enough to reject absurd input.  It protects the CLI, logs, derived paths and
# diagnostics, so it belongs to the product, not to the project policy.
MAX_TARGET_LENGTH: Final[int] = 200


@dataclass(frozen=True, slots=True)
class Target:
    """A value object representing a string already validated under a policy.

    A :class:`Target` should only be produced through :class:`TargetValidator`
    (the validated path) or the explicitly-unsafe internal constructor
    :meth:`from_trusted`.  The rest of the lifecycle must depend on this type
    rather than on arbitrary strings where a validated target is expected (R7,
    INV-04).
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError("Target.value must be a str")
        if self.value == "":
            # A Target is never empty (R4).  This guards the internal path too.
            raise ValueError("Target.value must not be empty")

    def __str__(self) -> str:
        return self.value

    @classmethod
    def from_trusted(cls, value: str) -> "Target":
        """Build a :class:`Target` from an already-trusted value.

        This bypasses policy validation and must only be used for values known
        to be valid (e.g. rehydrating a previously validated identity).  Normal
        creation must go through :class:`TargetValidator` (R7).
        """

        return cls(value=value)


@dataclass(frozen=True, slots=True)
class TargetPolicy:
    """The effective, resolved target policy declared by the project (R1).

    ``regex`` and ``example`` are mandatory and ``example`` must itself satisfy
    the policy; :meth:`compile` enforces both so a policy object is only ever
    built from a coherent configuration.
    """

    regex: str
    example: str
    case_sensitive: bool

    def compile(self) -> "CompiledTargetPolicy":
        """Compile the policy, validating regex and example (R2, R6).

        Raises
        ------
        TargetRegexInvalidError
            If ``regex`` is empty or does not compile with the standard engine.
        TargetExampleInvalidError
            If ``example`` is empty or does not satisfy the policy.
        """

        if not isinstance(self.regex, str) or self.regex == "":
            raise TargetRegexInvalidError("target.regex must be a non-empty pattern")

        flags = 0 if self.case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(self.regex, flags)
        except re.error as exc:
            raise TargetRegexInvalidError(
                f'target.regex does not compile: {self.regex!r} ({exc})'
            ) from exc

        if not isinstance(self.example, str) or self.example == "":
            raise TargetExampleInvalidError("target.example must be a non-empty value")

        # The shipped example must satisfy the very policy used to validate
        # targets (R6).  fullmatch enforces exact-match semantics (INV-02).
        if pattern.fullmatch(self.example) is None:
            raise TargetExampleInvalidError(
                f'target.example {self.example!r} does not match target.regex '
                f'{self.regex!r}'
            )

        return CompiledTargetPolicy(pattern=pattern, policy=self)


@dataclass(frozen=True, slots=True)
class CompiledTargetPolicy:
    """A :class:`TargetPolicy` with its compiled, full-match-ready pattern.

    Holding the compiled pattern lets the same policy validate many candidates
    without recompiling, while keeping the original declared values available
    for diagnostics.
    """

    pattern: re.Pattern[str]
    policy: TargetPolicy


class TargetValidator:
    """Shared, reusable target validator (R10).

    A single instance is built from a :class:`TargetPolicy` and validates any
    number of candidates.  CLI, lifecycle and future commands must reuse this
    service instead of scattering their own regex checks (R10).
    """

    def __init__(self, policy: TargetPolicy) -> None:
        # Compiling here surfaces TARGET_REGEX_INVALID / TARGET_EXAMPLE_INVALID
        # before any candidate is validated (R2).
        self._compiled = policy.compile()

    @property
    def policy(self) -> TargetPolicy:
        return self._compiled.policy

    def validate(self, candidate: str) -> Target:
        """Validate ``candidate`` against the policy and return a :class:`Target`.

        The result depends only on ``candidate`` and the policy (INV-03, R9):
        no Git, worktree, history or external lookup is consulted.

        Raises
        ------
        TargetInvalidError
            If ``candidate`` is empty/blank or does not fully match the policy.
        TargetTooLongError
            If ``candidate`` exceeds :data:`MAX_TARGET_LENGTH`.
        """

        if not isinstance(candidate, str):
            raise TargetInvalidError(self._invalid_message(str(candidate)))

        # Length is checked before matching so a pathological input never
        # reaches the regex engine (R12).
        if len(candidate) > MAX_TARGET_LENGTH:
            raise TargetTooLongError(
                f"Target demasiado largo: {len(candidate)} caracteres "
                f"(máximo permitido {MAX_TARGET_LENGTH})."
            )

        # Empty or whitespace-only candidates are rejected (R4).  This spec
        # does not trim; normalization is E1-S2's responsibility.
        if candidate == "" or candidate.strip() == "":
            raise TargetInvalidError(self._invalid_message(candidate))

        # Exact, full-value match regardless of anchors in the project regex
        # (INV-02, R3).
        if self._compiled.pattern.fullmatch(candidate) is None:
            raise TargetInvalidError(self._invalid_message(candidate))

        return Target.from_trusted(candidate)

    def _invalid_message(self, candidate: str) -> str:
        """Build the human-facing diagnostic for an invalid candidate (R8).

        Includes the received value and the configured example.  The full regex
        is not printed for readability but stays available on the policy for
        detailed diagnostics.
        """

        return (
            f'Target inválido: "{candidate}".\n'
            "Esperado un valor compatible con la convención del proyecto.\n"
            f"Ejemplo: {self._compiled.policy.example}"
        )



@dataclass(frozen=True, slots=True)
class NormalizationRules:
    """Effective, resolved normalization rules for :class:`TargetNormalizer`.

    This mirrors ``[target.normalization]`` but lives in the core so the
    normalizer stays independent of the configuration source.  The config layer
    builds it from :class:`~ramalio.config.models.TargetNormalizationConfig`.

    Fields
    ------
    trim
        Strip leading/trailing whitespace (R3).
    replace_spaces
        When non-empty, every internal whitespace run is replaced by this
        separator (R4).  Empty disables the rule.
    collapse_dashes
        Collapse repeated ``-`` runs into a single dash (R5).
    lowercase_slug
        Lowercase the slug portion while preserving a configurable prefix (R6).
    slug_separator
        Separator used to split segments for slug lowercasing (R6).
    preserve_prefix_segments
        Number of leading segments kept verbatim before lowercasing (R6).  Kept
        generic so no project-specific structure is encoded in the core (7.3).
    """

    trim: bool
    replace_spaces: str
    collapse_dashes: bool
    lowercase_slug: bool
    slug_separator: str
    preserve_prefix_segments: int


# Whitespace run matcher for replace_spaces (R4).  A fixed, internal pattern:
# never a user-provided regex, and no shell is ever involved.
_WHITESPACE_RUN: Final[re.Pattern[str]] = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class TargetNormalizationResult:
    """Outcome of normalizing a raw value into a canonical :class:`Target` (R10).

    Exposes the raw and normalized strings plus ``changed`` so the CLI can show
    a transformation without touching domain logic (INV-08, R17).  ``target``
    is the validated canonical identity used for all downstream derivation
    (INV-05).
    """

    raw_value: str
    normalized_value: str
    target: Target

    @property
    def changed(self) -> bool:
        """Whether normalization altered the raw input (R10, R17)."""

        return self.raw_value != self.normalized_value


class TargetNormalizer:
    """Configurable, deterministic normalization pipeline (E1-S2).

    The pipeline runs rules in a fixed order regardless of TOML key order
    (INV-02, R2)::

        trim -> replace_spaces -> collapse_dashes -> lowercase_slug -> validate

    Validation is delegated to :class:`TargetValidator` (INV-03, R9): a value is
    never a :class:`Target` until E1-S1 accepts it.  The normalizer transforms
    syntax only; it never interprets the meaning of the ticket or slug (INV-04).
    """

    def __init__(self, rules: NormalizationRules, validator: TargetValidator) -> None:
        self._rules = rules
        self._validator = validator

    @property
    def rules(self) -> NormalizationRules:
        return self._rules

    def normalize(self, raw_value: str) -> TargetNormalizationResult:
        """Normalize ``raw_value`` and return a validated result.

        Raises
        ------
        TargetNormalizationFailedError
            If a rule cannot be applied unambiguously (R7).
        TargetNormalizationEmptyError
            If normalization collapses the value to empty (R8).
        TargetInvalidError / TargetTooLongError
            If the normalized value does not satisfy the policy (R9).
        """

        if not isinstance(raw_value, str):
            raise TargetNormalizationFailedError(
                "El valor a normalizar debe ser una cadena."
            )

        normalized = self._apply_pipeline(raw_value)

        # A value that collapses to empty must fail before building a Target
        # (R8), and before validation so the diagnostic is specific.
        if normalized == "":
            raise TargetNormalizationEmptyError(
                f'La normalización de "{raw_value}" produjo un valor vacío.'
            )

        # INV-03 / R9: the normalized value is not a target until E1-S1 accepts
        # it.  Any regex/length failure surfaces as TARGET_INVALID / TARGET_TOO_LONG.
        target = self._validator.validate(normalized)

        return TargetNormalizationResult(
            raw_value=raw_value,
            normalized_value=normalized,
            target=target,
        )

    def _apply_pipeline(self, value: str) -> str:
        """Run the fixed-order transformation pipeline (R2)."""

        if self._rules.trim:
            value = value.strip()

        if self._rules.replace_spaces != "":
            value = _WHITESPACE_RUN.sub(self._rules.replace_spaces, value)

        if self._rules.collapse_dashes:
            # Applies to '-' only; other separators are out of scope (R5).
            value = re.sub(r"-{2,}", "-", value)

        if self._rules.lowercase_slug:
            value = self._lowercase_slug(value)

        return value

    def _lowercase_slug(self, value: str) -> str:
        """Lowercase the slug portion, preserving configured prefix segments (R6).

        The rule is fully generic: it splits on ``slug_separator``, keeps the
        first ``preserve_prefix_segments`` segments verbatim and lowercases the
        rest.  No project-specific pattern (e.g. ``E<n>-S<n>``) is hardcoded
        (7.3, INV-04).
        """

        separator = self._rules.slug_separator
        preserve = self._rules.preserve_prefix_segments

        if separator == "":
            # Degenerate configuration: without a separator the slug boundary is
            # ambiguous, so refuse rather than invent one (R7).
            raise TargetNormalizationFailedError(
                "lowercase_slug requiere un slug_separator no vacío."
            )

        segments = value.split(separator)
        if preserve >= len(segments):
            # Nothing left to lowercase; preserving everything is a no-op that
            # keeps the value verbatim (conservative, R7).
            return value

        head = segments[:preserve]
        tail = [segment.lower() for segment in segments[preserve:]]
        return separator.join([*head, *tail])
