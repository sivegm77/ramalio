"""Bridge between resolved configuration and the target validator (E1-S1).

E1-S0 loads ``[target].regex``/``example``/``case_sensitive`` as *data* without
interpreting them (they are optional at the structural level).  This module
turns that resolved data into a concrete :class:`~ramalio.core.target.
TargetPolicy` and, from it, a shared :class:`~ramalio.core.target.
TargetValidator`.

Keeping this glue in the config layer keeps the core agnostic of configuration
sources while still guaranteeing there is a single validation service reused by
the CLI, lifecycle and future commands (R7, R10).  No project-specific regex is
ever hardcoded here.
"""

from __future__ import annotations

from ..core.errors import TargetExampleInvalidError, TargetRegexInvalidError
from ..core.naming import BranchRules, WorkspaceNaming, WorktreeRules
from ..core.target import (
    NormalizationRules,
    TargetNormalizer,
    TargetPolicy,
    TargetValidator,
)
from .models import ResolvedProjectConfig


def build_target_policy(config: ResolvedProjectConfig) -> TargetPolicy:
    """Build the effective :class:`TargetPolicy` from resolved configuration.

    ``regex`` and ``example`` are mandatory for target validation (R1); they are
    structurally optional in E1-S0 because their semantics belong to this spec.

    Raises
    ------
    TargetRegexInvalidError
        If ``target.regex`` is absent or empty.
    TargetExampleInvalidError
        If ``target.example`` is absent or empty.
    """

    target = config.target

    if target.regex is None or target.regex == "":
        raise TargetRegexInvalidError("target.regex is required and must be non-empty")

    if target.example is None or target.example == "":
        raise TargetExampleInvalidError(
            "target.example is required and must be non-empty"
        )

    return TargetPolicy(
        regex=target.regex,
        example=target.example,
        case_sensitive=target.case_sensitive,
    )


def build_target_validator(config: ResolvedProjectConfig) -> TargetValidator:
    """Build the shared :class:`TargetValidator` for a resolved project (R7, R10).

    Constructing the validator compiles the regex and checks the example, so a
    broken policy is surfaced (``TARGET_REGEX_INVALID`` / ``TARGET_EXAMPLE_INVALID``)
    before any candidate is validated (R2, R6).
    """

    return TargetValidator(build_target_policy(config))


def build_normalization_rules(config: ResolvedProjectConfig) -> NormalizationRules:
    """Translate resolved config into core :class:`NormalizationRules` (E1-S2).

    Keeping this mapping in the config layer lets the core normalizer stay
    agnostic of the configuration source (7.1).
    """

    normalization = config.target.normalization
    return NormalizationRules(
        trim=normalization.trim,
        replace_spaces=normalization.replace_spaces,
        collapse_dashes=normalization.collapse_dashes,
        lowercase_slug=normalization.lowercase_slug,
        slug_separator=normalization.slug_separator,
        preserve_prefix_segments=normalization.preserve_prefix_segments,
    )


def build_target_normalizer(config: ResolvedProjectConfig) -> TargetNormalizer:
    """Build the :class:`TargetNormalizer` bound to the project's validator (E1-S2).

    The normalizer runs the configured pipeline and always finishes by
    validating through E1-S1 (INV-03), so a broken target policy is surfaced at
    construction time (R2, R6).
    """

    return TargetNormalizer(
        build_normalization_rules(config), build_target_validator(config)
    )


def build_workspace_naming(config: ResolvedProjectConfig) -> WorkspaceNaming:
    """Build the :class:`WorkspaceNaming` service from resolved config (E1-S2 R11/R12).

    Pattern validity is enforced lazily during derivation so both branch and
    worktree defects surface with their own stable codes.
    """

    return WorkspaceNaming(
        branch=BranchRules(pattern=config.branch.pattern),
        worktree=WorktreeRules(
            directory=config.worktree.directory,
            pattern=config.worktree.pattern,
        ),
    )
