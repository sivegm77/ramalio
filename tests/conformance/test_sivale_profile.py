"""SiVale as a client project of ramalio (E8-S0).

Proves SiVale's real conventions are fully expressible via configuration +
existing capabilities/integrations, with no SiVale-specific code in the core
(INV-01/INV-03/AC-07).  External tools (docker/tmux/kiro) are not required to
validate the configuration itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ramalio.config.loader import resolve_project_config
from ramalio.config.target import (
    build_target_normalizer,
    build_workspace_naming,
)
from ramalio.core.doctor import CheckStatus, DoctorService

_SIVALE_TOML = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "examples"
    / "sivale.ramalio.toml"
).read_text(encoding="utf-8")


def _make_sivale_repo(tmp_path: Path) -> Path:
    root = tmp_path / "sivale"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    import os

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
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "-m", "seed"],
        check=True,
        capture_output=True,
    )
    (root / ".ramalio.toml").write_text(_SIVALE_TOML, encoding="utf-8")
    return root


@pytest.fixture
def sivale(tmp_path: Path) -> Path:
    return _make_sivale_repo(tmp_path)


# --- AC: configuration loads and validates ---------------------------------


def test_config_loads(sivale: Path) -> None:
    config = resolve_project_config(sivale)
    assert config.project.name == "sivale-zurich"
    assert config.project.base_branch == "main"
    assert config.branch.pattern == "spec/{target}"
    assert config.ports.enabled is True
    assert "runtime" in config.capabilities
    assert config.capabilities["runtime"].options["driver"] == "docker-compose"
    assert "tmux" in config.capabilities
    assert "kiro" in config.integrations


# --- AC-02: target normalizes and validates without special code -----------


def test_ac02_sivale_target_normalizes(sivale: Path) -> None:
    config = resolve_project_config(sivale)
    normalizer = build_target_normalizer(config)
    # Uppercase slug portion is lowercased; E7-S8 prefix preserved.
    result = normalizer.normalize("E7-S8-Convergencia-Schema-Tests")
    assert result.target.value == "E7-S8-convergencia-schema-tests"


def test_invalid_sivale_target_rejected(sivale: Path) -> None:
    from ramalio.core.errors import TargetInvalidError

    config = resolve_project_config(sivale)
    normalizer = build_target_normalizer(config)
    with pytest.raises(TargetInvalidError):
        normalizer.normalize("not-a-spec-target")


# --- AC-03: branch/path derived from configuration -------------------------


def test_ac03_branch_and_path_derived(sivale: Path) -> None:
    config = resolve_project_config(sivale)
    normalizer = build_target_normalizer(config)
    naming = build_workspace_naming(config)
    target = normalizer.normalize("E7-S8-convergencia-schema-tests").target
    identity = naming.resolve(target)
    assert identity.branch_name == "spec/E7-S8-convergencia-schema-tests"
    assert str(identity.worktree_path) == ".local-wt/E7-S8-convergencia-schema-tests"


# --- AC-01: doctor recognizes the project with a valid configuration -------


def test_ac01_doctor_recognizes_project(sivale: Path) -> None:
    report = DoctorService(start=sivale).run()
    by_id = {r.check_id: r for r in report.results}
    # The configuration itself is valid, regardless of whether external tools
    # (docker/tmux/kiro) happen to be installed on this machine.
    assert by_id["CONFIG_PRESENT"].status == CheckStatus.PASS
    assert by_id["CONFIG_VALID"].status == CheckStatus.PASS
    assert by_id["TARGET_POLICY"].status == CheckStatus.PASS
    assert by_id["BRANCH_PATTERN"].status == CheckStatus.PASS
    assert by_id["WORKTREE_PATTERN"].status == CheckStatus.PASS
    assert by_id["BASE_BRANCH"].status == CheckStatus.PASS


# --- AC-04: enabled capabilities appear in status --------------------------


def test_ac04_capabilities_in_status(sivale: Path) -> None:
    from ramalio.capabilities import (
        BaseCapability,
        CapabilityContext,
        CapabilityRegistry,
        CapabilityState,
    )
    from ramalio.capabilities.base import CapabilityStatus

    # Use lightweight fakes for the enabled capability names so status can be
    # exercised without docker/tmux installed (the point is that they PARTICIPATE
    # from configuration, AC-04).
    class _FakeRuntime(BaseCapability):
        capability_name = "runtime"

        def is_enabled(self, context) -> bool:
            return context.capability_config(self.name) is not None

        def status(self, context) -> CapabilityStatus:
            return CapabilityStatus(self.name, CapabilityState.READY, "fake runtime")

    class _FakeTmux(BaseCapability):
        capability_name = "tmux"

        def status(self, context) -> CapabilityStatus:
            if not self.is_enabled(context):
                return CapabilityStatus(self.name, CapabilityState.DISABLED, "off")
            return CapabilityStatus(self.name, CapabilityState.STOPPED, "fake tmux")

    config = resolve_project_config(sivale)
    identity = build_workspace_naming(config).resolve(
        build_target_normalizer(config).normalize(
            "E1-S0-arranque-inicial"
        ).target
    )
    registry = CapabilityRegistry.with_capabilities([_FakeRuntime(), _FakeTmux()])
    ctx = CapabilityContext(config=config, identity=identity)
    names = {s.name for s in registry.collect_status(ctx)}
    assert "runtime" in names
    assert "tmux" in names


# --- AC-05/AC-07: the same core serves a non-SiVale project unchanged ------


def test_ac05_other_project_works_without_docker_tmux_kiro(tmp_path: Path) -> None:
    # A plain Git-only project (no docker/tmux/kiro) uses the exact same core
    # and validates cleanly, proving SiVale's config adds no core dependency.
    root = tmp_path / "other"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    import os

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
    (root / ".ramalio.toml").write_text(
        """
[project]
name = "other-project"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "{target}"
""",
        encoding="utf-8",
    )
    report = DoctorService(start=root).run()
    # A Git-only project with no capabilities is fully healthy.
    assert report.global_status == CheckStatus.PASS


# --- AC-07: no SiVale coupling in the core (no project-name branching) ------


def test_ac07_no_sivale_conditionals_in_core() -> None:
    # The core must not branch on SiVale-specific identifiers. We look for
    # actual coupling (the project name or developer var used as a value/compare),
    # not prose in comments that documents the ABSENCE of coupling.
    import re

    src = Path(__file__).resolve().parents[2] / "src" / "ramalio"
    # Patterns that would indicate real coupling: a literal "sivale"/"zurich"
    # string used in code (quoted), or the KIRO_DEVELOPER env var being read.
    coupling = re.compile(
        r"""["'](sivale|zurich)[^"']*["']|KIRO_DEVELOPER|KIRO_PROJECT_ROOT""",
        re.IGNORECASE,
    )
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            # Skip comment-only lines and docstring prose.
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if coupling.search(line):
                offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert offenders == [], f"core has SiVale coupling: {offenders}"
