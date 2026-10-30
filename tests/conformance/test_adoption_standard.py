"""Adoption standard validation (E9-S2).

Verifies the documentation artifacts exist and that following the minimal
template + example profiles yields a working lifecycle, i.e. onboarding is
reproducible from the docs alone (AC-01..AC-12, R19).
"""

from __future__ import annotations

import os
import subprocess
from io import StringIO
from pathlib import Path

import pytest

from ramalio.cli import main
from ramalio.config.loader import resolve_project_config
from ramalio.core.result import ExitCode

_DOCS = Path(__file__).resolve().parents[2] / "docs"
_EXAMPLES = _DOCS / "examples"


# --- AC-01/AC-04/AC-05/AC-06/AC-08: required docs exist --------------------


@pytest.mark.parametrize(
    "relpath",
    [
        "getting-started.md",
        "adoption-guide.md",
        "lifecycle.md",
        "capabilities.md",
        "integrations.md",
        "migration-from-scripts.md",
        "troubleshooting.md",
        "versioning-and-compatibility.md",
        "installation.md",
        "examples/minimal.ramalio.toml",
    ],
)
def test_required_docs_present(relpath: str) -> None:
    assert (_DOCS / relpath).is_file(), f"missing doc: {relpath}"


def test_adoption_guide_has_checklist_and_governance() -> None:
    text = (_DOCS / "adoption-guide.md").read_text(encoding="utf-8")
    assert "Checklist de adopción" in text
    assert "No secrets in" in text and ".ramalio.toml" in text  # R13
    assert "Definition of adopted" in text  # R7
    assert "Proponer una extensión" in text  # R16/AC-09


def test_catalogs_present() -> None:
    caps = (_DOCS / "capabilities.md").read_text(encoding="utf-8")
    for name in ("processes", "tmux", "runtime", "ports", "tunnel"):
        assert name in caps
    ints = (_DOCS / "integrations.md").read_text(encoding="utf-8")
    for name in ("kiro", "vscode", "codex", "claude"):
        assert name in ints


# --- AC-02: minimal template has no mandatory capabilities -----------------


def test_minimal_template_no_capabilities(tmp_path: Path) -> None:
    project = _apply_profile(tmp_path, (_EXAMPLES / "minimal.ramalio.toml").read_text(encoding="utf-8"))
    config = resolve_project_config(project)
    assert dict(config.capabilities) == {}
    assert dict(config.integrations) == {}
    assert config.ports.enabled is False


# --- AC-03: three example profiles exist and load --------------------------


@pytest.mark.parametrize(
    "profile_file",
    [
        "minimal.ramalio.toml",
        "second-pilot.ramalio.toml",
        "sivale.ramalio.toml",
    ],
)
def test_example_profiles_load(tmp_path: Path, profile_file: str) -> None:
    project = _apply_profile(
        tmp_path / profile_file.split(".")[0],
        (_EXAMPLES / profile_file).read_text(encoding="utf-8"),
    )
    # Loading validates structure without touching the core.
    config = resolve_project_config(project)
    assert config.project.name


# --- AC-10/R19: reproducible onboarding with the minimal template ----------


def test_reproducible_onboarding_lifecycle(tmp_path: Path) -> None:
    project = _apply_profile(
        tmp_path,
        (_EXAMPLES / "minimal.ramalio.toml").read_text(encoding="utf-8"),
    )

    def cli(*args: str):
        stdout, stderr = StringIO(), StringIO()
        prev = os.getcwd()
        os.chdir(project)
        try:
            code = main(list(args), stdout=stdout, stderr=stderr)
        finally:
            os.chdir(prev)
        return code, stdout.getvalue()

    assert cli("doctor")[0] == ExitCode.OK
    assert cli("init", "my-feature")[0] == ExitCode.OK
    assert "State: READY" in cli("status", "my-feature")[1]
    assert cli("destroy", "my-feature")[0] == ExitCode.OK


# --- helper ----------------------------------------------------------------


def _apply_profile(root: Path, toml: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    for k, v in {
        "GIT_AUTHOR_NAME": "c",
        "GIT_AUTHOR_EMAIL": "c@e.com",
        "GIT_COMMITTER_NAME": "c",
        "GIT_COMMITTER_EMAIL": "c@e.com",
    }.items():
        os.environ.setdefault(k, v)
    subprocess.run(
        ["git", "-C", str(root), "symbolic-ref", "HEAD", "refs/heads/main"],
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    (root / ".ramalio.toml").write_text(toml, encoding="utf-8")
    return root
