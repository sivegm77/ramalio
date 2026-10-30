"""Typed, immutable configuration model for E1 (R4-R8).

These structures represent the *effective* configuration after defaults,
personal configuration and project configuration have been merged and
validated.  They intentionally model only the conceptual areas frozen for E1;
target/branch/worktree semantics are validated by later specs.

The model never stores raw, unresolved source fragments (7.3): each field holds
a resolved value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """``[project]`` section (R5)."""

    name: str
    base_branch: str


@dataclass(frozen=True, slots=True)
class MetaConfig:
    """``[meta]`` section: configuration schema versioning (E9-S1 R11).

    ``schema_version`` lets the CLI check compatibility explicitly instead of
    assuming every future TOML is compatible.  Defaults to the CLI's supported
    schema when absent, so existing configs keep working.
    """

    schema_version: int


@dataclass(frozen=True, slots=True)
class TargetNormalizationConfig:
    """``[target.normalization]`` section (R6, E1-S2 R1/R6).

    Loaded verbatim in E1-S0; the normalization pipeline (E1-S2) interprets
    these fields.  ``slug_separator`` and ``preserve_prefix_segments`` keep the
    slug-lowercasing rule generic so no project-specific structure (e.g.
    ``E<n>-S<n>``) is encoded in the core (7.3).
    """

    trim: bool
    lowercase_slug: bool
    replace_spaces: str
    collapse_dashes: bool
    slug_separator: str
    preserve_prefix_segments: int


@dataclass(frozen=True, slots=True)
class TargetConfig:
    """``[target]`` section (R6).

    ``regex``/``example`` are optional in E1 because target semantics are
    validated later (E1-S1).  Values are loaded, not interpreted.
    """

    regex: str | None
    example: str | None
    case_sensitive: bool
    normalization: TargetNormalizationConfig


@dataclass(frozen=True, slots=True)
class WorktreeConfig:
    """``[worktree]`` section (R7).

    Pattern expansion belongs to E1-S2; here we only carry declared values.
    """

    directory: str
    pattern: str


@dataclass(frozen=True, slots=True)
class BranchConfig:
    """``[branch]`` section (R7, E2-S3 R10).

    ``delete_on_destroy`` is an opt-in, conservative branch-cleanup policy for
    ``destroy``.  Its safe default is ``False``: the absence of the field means
    the branch is preserved (E2-S3 R10/R11, INV-04).
    """

    pattern: str
    delete_on_destroy: bool = False


@dataclass(frozen=True, slots=True)
class PortsConfig:
    """``[ports]`` section (E6-S1 R1).

    Optional per-target port allocation.  Disabled by default so a project that
    does not need ports carries none of this behavior (INV: ports are optional).
    """

    enabled: bool = False
    start: int = 8100
    size: int = 20


@dataclass(frozen=True, slots=True)
class CapabilityConfig:
    """A single ``[capabilities.<name>]`` entry (R8).

    ``options`` preserves any additional declared keys so future specs can
    interpret them.  E1 only loads capabilities; it never executes them.
    """

    name: str
    enabled: bool
    options: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class IntegrationConfig:
    """A single ``[integrations.<name>]`` entry (E5-S2 R1, E9-S3).

    ``command`` is the canonical, structured argv of the integration: an
    immutable tuple where each element is exactly one argument (E9-S3 R1/INV-02).
    Configuration is data (7.8/INV-02): a shell string is never accepted and no
    implicit tokenization (``str.split``/``shlex.split``) is applied (E9-S3 R2).
    It is ``None`` when the project declares no override and the adapter default
    applies.

    ``pass_env`` is the only supported, explicit mechanism to forward host
    environment variables into the controlled child environment (E9-S3 R4/R5).
    It is an allowlist of variable *names* (never inline ``KEY=value`` values and
    never secret values); the default is empty so nothing beyond the controlled
    base is inherited (E9-S3 INV-03/INV-04/INV-06). ``inherit_env`` is not part
    of the public contract (E9-S3 R8/INV-05).
    """

    name: str
    enabled: bool
    command: tuple[str, ...] | None = None
    pass_env: tuple[str, ...] = ()
    options: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))


@dataclass(frozen=True, slots=True)
class ResolvedProjectConfig:
    """Effective, immutable configuration handed to the rest of the product.

    Consumers must depend on this model instead of reading the TOML file (R14).
    Given identical input sources, the resolved configuration is deterministic
    (INV-07).
    """

    repository_root: Path
    project: ProjectConfig
    target: TargetConfig
    worktree: WorktreeConfig
    branch: BranchConfig
    meta: MetaConfig = field(default_factory=lambda: MetaConfig(schema_version=1))
    ports: PortsConfig = field(default_factory=PortsConfig)
    capabilities: Mapping[str, CapabilityConfig] = field(
        default_factory=lambda: MappingProxyType({})
    )
    integrations: Mapping[str, IntegrationConfig] = field(
        default_factory=lambda: MappingProxyType({})
    )
