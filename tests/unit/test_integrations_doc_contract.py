"""Documented integration examples are executable contract (E9-S3 R13/R14/AC-09).

The TOML snippets published in ``docs/integrations.md`` and the official example
``docs/examples/sivale.ramalio.toml`` are loaded here through the *real*
config loader/validator, so documentation, model and validation can never drift
apart (E9-S3 INV-01/AC-10). The schema-compatibility decision (E9-S3 R12/AC-11)
is pinned by an explicit test.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from ramalio import SUPPORTED_CONFIG_SCHEMA
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import ProjectConfigInvalidError

_DOCS = Path(__file__).resolve().parents[2] / "docs"


def _base_config(integrations_block: str) -> str:
    return f"""
[project]
name = "docs-example"
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
{integrations_block}
"""


def _integration_snippets(markdown: str) -> list[str]:
    """Extract fenced ```toml blocks that declare an integration."""

    blocks = re.findall(r"```toml\n(.*?)```", markdown, flags=re.DOTALL)
    return [b for b in blocks if "[integrations." in b]


def _load_snippet(snippet: str, git_repo: Path, write_config):
    """Load a documented snippet through the real loader.

    A snippet may be a full config (declares ``[project]``) or a partial
    integrations fragment; the latter is wrapped in a minimal valid base so it
    can be loaded literally (E9-S3 R13).
    """

    body = snippet if "[project]" in snippet else _base_config(snippet)
    write_config(git_repo, body)
    return resolve_project_config(git_repo)


def test_docs_integrations_snippets_load_via_real_loader(
    git_repo_with_commit: Path, write_config
) -> None:
    # E9-S3 R13/AC-09: every documented integration TOML snippet must load
    # through the real loader. Both docs reconciled by this spec are covered.
    docs = [_DOCS / "integrations.md", _DOCS / "configuracion.md"]
    snippets: list[str] = []
    for doc in docs:
        snippets.extend(_integration_snippets(doc.read_text(encoding="utf-8")))
    # The documentation must contain at least the canonical command example.
    assert snippets, "no integration TOML snippet found in the reconciled docs"

    for snippet in snippets:
        resolved = _load_snippet(snippet, git_repo_with_commit, write_config)
        # Every declared integration exposes a structured argv contract.
        for entry in resolved.integrations.values():
            if entry.command is not None:
                assert isinstance(entry.command, tuple)
                assert all(isinstance(part, str) and part for part in entry.command)
            assert isinstance(entry.pass_env, tuple)


def test_docs_configuracion_integration_snippet_loads(
    git_repo_with_commit: Path, write_config
) -> None:
    """R13/AC-09: the integration example in docs/configuracion.md (reconciled
    by E9-S3) is loaded literally through the real loader."""

    markdown = (_DOCS / "configuracion.md").read_text(encoding="utf-8")
    snippets = _integration_snippets(markdown)
    assert snippets, "docs/configuracion.md declares no integration TOML snippet"
    for snippet in snippets:
        resolved = _load_snippet(snippet, git_repo_with_commit, write_config)
        assert resolved.integrations["kiro"].command == ("kiro-cli", "--v3")


def test_docs_canonical_kiro_example_yields_exact_argv(
    git_repo_with_commit: Path, write_config
) -> None:
    write_config(
        git_repo_with_commit,
        _base_config(
            '\n[integrations.kiro]\nenabled = true\ncommand = ["kiro-cli", "--v3"]\n'
        ),
    )
    resolved = resolve_project_config(git_repo_with_commit)
    assert resolved.integrations["kiro"].command == ("kiro-cli", "--v3")


def test_official_sivale_example_loads(git_repo_with_commit: Path, write_config) -> None:
    example = (_DOCS / "examples" / "sivale.ramalio.toml").read_text(
        encoding="utf-8"
    )
    # Load the published example through the real loader; the kiro integration
    # command must be structured argv (AC-09/AC-10).
    write_config(git_repo_with_commit, example)
    resolved = resolve_project_config(git_repo_with_commit)
    assert resolved.integrations["kiro"].command == ("kiro-cli",)


def test_sivale_example_toml_declares_structured_command() -> None:
    example = (_DOCS / "examples" / "sivale.ramalio.toml").read_text(
        encoding="utf-8"
    )
    parsed = tomllib.loads(example)
    command = parsed["integrations"]["kiro"]["command"]
    # The example itself uses an array, not a shell string (E9-S3 R1/AC-02).
    assert isinstance(command, list)
    assert command == ["kiro-cli"]


# --- R12 / AC-11: schema-compatibility decision ----------------------------


def test_schema_decision_no_bump_required() -> None:
    """E9-S3 R12 decision, pinned by test.

    The convergence keeps the supported config schema at v1 (design §7.4
    option 1): no official release distributed the divergent contract (string
    ``command`` / ``inherit_env``) before E9-S3, so it is corrected in place
    without a migration. That precondition is a *historical* fact recorded, with
    the concrete checks performed, in the spec (section 14); it is deliberately
    NOT re-derived here as a dynamic invariant, because a legitimate future
    release of the already-correct contract must not turn this suite red.

    What this test pins is the durable property: the supported schema is v1, and
    the functional tests in this module demonstrate that the final integrations
    contract corresponds to schema v1. This fails on purpose if a change bumps
    the schema without revisiting the decision.
    """

    assert SUPPORTED_CONFIG_SCHEMA == 1


def test_schema_v1_config_without_meta_is_accepted(
    git_repo_with_commit: Path, write_config
) -> None:
    """The converged integrations contract is expressible under schema v1.

    A config that omits ``[meta]`` (schema assumed = supported) and uses the
    canonical argv ``command`` loads cleanly, demonstrating that the final
    contract belongs to schema v1 and needs no migration (E9-S3 R12/AC-11).
    """

    write_config(
        git_repo_with_commit,
        _base_config(
            '\n[integrations.kiro]\nenabled = true\n'
            'command = ["kiro-cli", "--v3"]\npass_env = ["AWS_PROFILE"]\n'
        ),
    )
    resolved = resolve_project_config(git_repo_with_commit)
    assert resolved.meta.schema_version == SUPPORTED_CONFIG_SCHEMA == 1
    assert resolved.integrations["kiro"].command == ("kiro-cli", "--v3")


def test_explicit_schema_v1_meta_is_accepted(
    git_repo_with_commit: Path, write_config
) -> None:
    """Declaring ``[meta].schema_version = 1`` explicitly with the converged
    contract is accepted, confirming no bump is required (E9-S3 R12)."""

    write_config(
        git_repo_with_commit,
        "[meta]\nschema_version = 1\n"
        + _base_config(
            '\n[integrations.kiro]\nenabled = true\ncommand = ["kiro-cli"]\n'
        ),
    )
    resolved = resolve_project_config(git_repo_with_commit)
    assert resolved.meta.schema_version == 1
    assert resolved.integrations["kiro"].command == ("kiro-cli",)


def test_string_command_is_rejected_after_convergence(
    git_repo_with_commit: Path, write_config
) -> None:
    """AC-02/AC-03: a shell string is not the canonical form and is rejected;
    no production path splits it into argv."""

    write_config(
        git_repo_with_commit,
        _base_config(
            '\n[integrations.kiro]\nenabled = true\ncommand = "kiro-cli --v3"\n'
        ),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)



def test_empty_command_array_is_rejected(
    git_repo_with_commit: Path, write_config
) -> None:
    """Case 3: an empty ``command`` array violates the contract (E9-S3 R3)."""

    write_config(
        git_repo_with_commit,
        _base_config('\n[integrations.kiro]\nenabled = true\ncommand = []\n'),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)


def test_command_array_with_non_string_is_rejected(
    git_repo_with_commit: Path, write_config
) -> None:
    """Case 5: a non-string argv element violates the contract (E9-S3 R3)."""

    write_config(
        git_repo_with_commit,
        _base_config('\n[integrations.kiro]\nenabled = true\ncommand = ["kiro-cli", 3]\n'),
    )
    with pytest.raises(ProjectConfigInvalidError):
        resolve_project_config(git_repo_with_commit)
