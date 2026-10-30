"""Tests for the capability contract and registry (E4-S0).

Uses fake capabilities to prove the core never needs to know concrete
implementations: registration, enable/disable, config validation, status
integration, doctor contribution, error isolation, duplicate and unknown
handling (AC-01..AC-08).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from ramalio.capabilities import (
    BaseCapability,
    CapabilityContext,
    CapabilityRegistry,
    CapabilityState,
    default_registry,
)
from ramalio.capabilities.base import (
    CapabilityDoctorCheck,
    CapabilityStatus,
    DoctorCheckStatus,
)
from ramalio.config.loader import resolve_project_config
from ramalio.core.errors import (
    CapabilityConfigInvalidError,
    CapabilityDuplicateError,
    CapabilityUnknownError,
)

_CONFIG_TEMPLATE = """
[project]
name = "simple-git"
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
{capabilities}
"""


def _config(project_root: Path, write_config, capabilities: str = ""):
    write_config(project_root, _CONFIG_TEMPLATE.format(capabilities=capabilities))
    return resolve_project_config(project_root)


def _ctx(config) -> CapabilityContext:
    return CapabilityContext(config=config)


# --- fake capabilities ------------------------------------------------------


class _ReadyCapability(BaseCapability):
    capability_name = "fake-ready"


class _ActiveCapability(BaseCapability):
    capability_name = "fake-active"

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        if not self.is_enabled(context):
            return CapabilityStatus(
                self.name, CapabilityState.DISABLED, "disabled"
            )
        return CapabilityStatus(self.name, CapabilityState.ACTIVE, "running")


class _ExplodingCapability(BaseCapability):
    capability_name = "fake-boom"

    def status(self, context: CapabilityContext) -> CapabilityStatus:
        raise RuntimeError("kaboom")


class _StrictConfigCapability(BaseCapability):
    capability_name = "fake-strict"

    def validate_config(self, context: CapabilityContext) -> None:
        entry = context.capability_config(self.name)
        if entry is not None and "mode" not in entry.options:
            raise CapabilityConfigInvalidError(
                f"capability '{self.name}': 'mode' is required"
            )


class _DoctorCapability(BaseCapability):
    capability_name = "fake-doctor"

    def doctor_checks(
        self, context: CapabilityContext
    ) -> Sequence[CapabilityDoctorCheck]:
        return (
            CapabilityDoctorCheck(
                check_id="FAKE_DOCTOR_TOOL",
                status=DoctorCheckStatus.PASS,
                summary="fake tool available",
            ),
        )


# --- AC-01: register a fake capability -------------------------------------


def test_ac01_register_fake_capability() -> None:
    registry = CapabilityRegistry()
    registry.register(_ReadyCapability())
    assert registry.get("fake-ready") is not None
    assert [c.name for c in registry.all()] == ["fake-ready"]


# --- AC-02: duplicate registration fails -----------------------------------


def test_ac02_duplicate_registration_fails() -> None:
    registry = CapabilityRegistry()
    registry.register(_ReadyCapability())
    with pytest.raises(CapabilityDuplicateError):
        registry.register(_ReadyCapability())


# --- AC-03: disabled capability does not participate -----------------------


def test_ac03_disabled_capability_absent(
    git_repo_with_commit: Path, write_config
) -> None:
    config = _config(git_repo_with_commit, write_config)  # no capabilities
    registry = CapabilityRegistry.with_capabilities([_ReadyCapability()])
    assert registry.enabled(_ctx(config)) == ()
    assert registry.collect_status(_ctx(config)) == ()


# --- AC-04: enabled capability appears in status ---------------------------


def test_ac04_enabled_capability_in_status(
    git_repo_with_commit: Path, write_config
) -> None:
    caps = "\n[capabilities.fake-active]\nenabled = true\n"
    config = _config(git_repo_with_commit, write_config, caps)
    registry = CapabilityRegistry.with_capabilities([_ActiveCapability()])
    statuses = registry.collect_status(_ctx(config))
    assert len(statuses) == 1
    assert statuses[0].name == "fake-active"
    assert statuses[0].state == CapabilityState.ACTIVE


# --- AC-05: a failing capability does not collapse status ------------------


def test_ac05_failing_capability_isolated(
    git_repo_with_commit: Path, write_config
) -> None:
    caps = (
        "\n[capabilities.fake-boom]\nenabled = true\n"
        "\n[capabilities.fake-active]\nenabled = true\n"
    )
    config = _config(git_repo_with_commit, write_config, caps)
    registry = CapabilityRegistry.with_capabilities(
        [_ExplodingCapability(), _ActiveCapability()]
    )
    statuses = {s.name: s for s in registry.collect_status(_ctx(config))}
    # Both reported; the exploding one is ERROR, the other survives.
    assert statuses["fake-boom"].state == CapabilityState.ERROR
    assert statuses["fake-active"].state == CapabilityState.ACTIVE


# --- AC-06: doctor receives checks from the registry -----------------------


def test_ac06_doctor_checks_collected(
    git_repo_with_commit: Path, write_config
) -> None:
    config = _config(git_repo_with_commit, write_config)
    registry = CapabilityRegistry.with_capabilities([_DoctorCapability()])
    checks = registry.collect_doctor_checks(_ctx(config))
    assert any(c.check_id == "FAKE_DOCTOR_TOOL" for c in checks)


# --- AC-07: unknown capability in config fails explicitly ------------------


def test_ac07_unknown_capability_fails(
    git_repo_with_commit: Path, write_config
) -> None:
    caps = "\n[capabilities.mystery]\nenabled = true\n"
    config = _config(git_repo_with_commit, write_config, caps)
    registry = CapabilityRegistry.with_capabilities([_ReadyCapability()])
    with pytest.raises(CapabilityUnknownError):
        registry.verify_configuration(_ctx(config))


def test_disabled_unknown_capability_does_not_fail(
    git_repo_with_commit: Path, write_config
) -> None:
    # An unknown capability that is not enabled must not fail (R6/R13).
    caps = "\n[capabilities.mystery]\nenabled = false\n"
    config = _config(git_repo_with_commit, write_config, caps)
    registry = CapabilityRegistry.with_capabilities([_ReadyCapability()])
    registry.verify_configuration(_ctx(config))  # no raise


# --- config validation (R12) -----------------------------------------------


def test_capability_config_invalid(
    git_repo_with_commit: Path, write_config
) -> None:
    caps = "\n[capabilities.fake-strict]\nenabled = true\n"
    config = _config(git_repo_with_commit, write_config, caps)
    registry = CapabilityRegistry.with_capabilities([_StrictConfigCapability()])
    with pytest.raises(CapabilityConfigInvalidError):
        registry.verify_configuration(_ctx(config))


def test_capability_config_valid_with_field(
    git_repo_with_commit: Path, write_config
) -> None:
    caps = '\n[capabilities.fake-strict]\nenabled = true\nmode = "fast"\n'
    config = _config(git_repo_with_commit, write_config, caps)
    registry = CapabilityRegistry.with_capabilities([_StrictConfigCapability()])
    registry.verify_configuration(_ctx(config))  # no raise


# --- determinism (R14) ------------------------------------------------------


def test_registry_preserves_registration_order() -> None:
    registry = CapabilityRegistry.with_capabilities(
        [_ReadyCapability(), _ActiveCapability(), _DoctorCapability()]
    )
    assert [c.name for c in registry.all()] == [
        "fake-ready",
        "fake-active",
        "fake-doctor",
    ]


# --- default registry ships the processes capability (E4-S2) ---------------


def test_default_registry_contains_processes() -> None:
    names = [c.name for c in default_registry().all()]
    assert "processes" in names



# --- integration with status (E4-S0 R9/R10) --------------------------------


def test_status_includes_enabled_capabilities(
    git_repo_with_commit: Path, write_config, run_git
) -> None:
    from ramalio.core.status import GetWorkspaceStatusService

    caps = "\n[capabilities.fake-active]\nenabled = true\n"
    config = _config(git_repo_with_commit, write_config, caps)
    # Create a real workspace so state is READY.
    wt = (git_repo_with_commit / ".local-wt" / "feature-cap").resolve()
    run_git(git_repo_with_commit, "worktree", "add", "-b", "feature-cap", str(wt))

    registry = CapabilityRegistry.with_capabilities([_ActiveCapability()])
    service = GetWorkspaceStatusService(config, registry=registry)
    status = service.run("feature-cap")

    names = {c.name for c in status.capabilities}
    assert "fake-active" in names


def test_status_survives_capability_failure(
    git_repo_with_commit: Path, write_config, run_git
) -> None:
    from ramalio.core.status import GetWorkspaceStatusService

    caps = "\n[capabilities.fake-boom]\nenabled = true\n"
    config = _config(git_repo_with_commit, write_config, caps)
    wt = (git_repo_with_commit / ".local-wt" / "feature-boom").resolve()
    run_git(git_repo_with_commit, "worktree", "add", "-b", "feature-boom", str(wt))

    registry = CapabilityRegistry.with_capabilities([_ExplodingCapability()])
    service = GetWorkspaceStatusService(config, registry=registry)
    status = service.run("feature-boom")

    # Workspace status is still produced; the capability is ERROR.
    assert status.state.value in {"READY", "DIRTY"}
    assert any(
        c.name == "fake-boom" and c.state == CapabilityState.ERROR
        for c in status.capabilities
    )


# --- integration with doctor (E4-S0 R11) -----------------------------------


def test_doctor_includes_capability_checks(
    git_repo_with_commit: Path, write_config
) -> None:
    from ramalio.core.doctor import CheckStatus, DoctorService

    config_body = _CONFIG_TEMPLATE.format(capabilities="")
    write_config(git_repo_with_commit, config_body)

    registry = CapabilityRegistry.with_capabilities([_DoctorCapability()])
    report = DoctorService(start=git_repo_with_commit, registry=registry).run()

    assert any(r.check_id == "FAKE_DOCTOR_TOOL" for r in report.results)
    # Healthy project + passing capability check stays PASS.
    assert report.global_status == CheckStatus.PASS


def test_doctor_unknown_capability_fails(
    git_repo_with_commit: Path, write_config
) -> None:
    from ramalio.core.doctor import CheckStatus, DoctorService

    caps = "\n[capabilities.mystery]\nenabled = true\n"
    write_config(git_repo_with_commit, _CONFIG_TEMPLATE.format(capabilities=caps))
    registry = CapabilityRegistry.with_capabilities([_ReadyCapability()])
    report = DoctorService(start=git_repo_with_commit, registry=registry).run()

    # Unknown enabled capability -> FAIL via the EXTENSIONS section.
    assert report.global_status == CheckStatus.FAIL
