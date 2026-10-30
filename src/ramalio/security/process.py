"""Safe, argv-only external command execution and diagnostics redaction (E7-S2).

External commands run with ``shell=False`` and a structured argv (R7); a raw
shell string is never accepted here.  The environment is controlled explicitly:
the runner starts from a minimal allowlist of essential base variables (PATH,
HOME, locale, ...) instead of the full host environment, then overlays the exact
extra variables the caller passes, so unrelated host variables never silently
become product configuration (R13).  Diagnostics never dump the full environment
or secret-looking values (R14).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

# Substrings that mark a variable as likely sensitive; redacted in diagnostics.
_SECRET_MARKERS = ("token", "secret", "password", "passwd", "key", "credential")

# Minimal set of host variables an external tool legitimately needs to run
# (locate binaries, resolve $HOME, honor locale).  Everything else from the host
# is intentionally dropped so it cannot leak into a child as product config
# (R13).  Windows-only variables are included so the runner stays portable.
_BASE_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "TZ",
    "XDG_RUNTIME_DIR",
    # Windows portability.
    "SystemRoot",
    "SYSTEMROOT",
    "PATHEXT",
    "COMSPEC",
    "WINDIR",
)


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """A structured external command (R7)."""

    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str] = field(default_factory=dict)
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not self.argv or not all(isinstance(a, str) and a for a in self.argv):
            raise ValueError("CommandSpec.argv must be a non-empty list of strings")


def redact_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Return ``env`` with secret-looking values redacted for diagnostics (R14)."""

    redacted: dict[str, str] = {}
    for key, value in env.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


# Matches ``NAME=value`` (or ``NAME: value``) assignments in free-form
# diagnostic text (e.g. subprocess stderr), so secret-looking values can be
# masked before being embedded in an error message (E7-S2 R14).
_ASSIGNMENT_RE = re.compile(
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*(?P<sep>[=:])\s*(?P<value>\S+)"
)


def redact_diagnostic(text: str | None) -> str:
    """Redact secret-looking assignments from free-form diagnostic text (R14).

    External command output (stdout/stderr) is untrusted and may echo secrets
    such as ``ZROK_TOKEN=...`` or ``API_KEY=...``.  Before such text is embedded
    in an error message it must be sanitized: any ``NAME=value`` /
    ``NAME: value`` pair whose ``NAME`` looks sensitive has its value masked.
    This is a best-effort scrubber for the documented contract cases (TOKEN,
    PASSWORD, SECRET, KEY, CREDENTIAL, ...), not a universal secret detector.
    """

    if not text:
        return ""

    def _mask(match: "re.Match[str]") -> str:
        key = match.group("key")
        sep = match.group("sep")
        if any(marker in key.lower() for marker in _SECRET_MARKERS):
            return f"{key}{sep}***"
        return match.group(0)

    return _ASSIGNMENT_RE.sub(_mask, text)


class SafeProcessRunner:
    """Runs :class:`CommandSpec` commands with shell=False (R7/R13).

    The environment is always the controlled base (an allowlist of essential
    host variables) plus the caller's explicit overlay. There is no full-host
    inheritance switch: unrelated host variables never silently become product
    configuration (E7-S2 R13, E9-S3 INV-03/INV-05).
    """

    def run(
        self, spec: CommandSpec, *, capture: bool = True
    ) -> subprocess.CompletedProcess:
        """Execute ``spec`` synchronously.  Never uses a shell (R7)."""

        env = self._merged_env(spec.env)
        return subprocess.run(  # noqa: S603 - argv list, shell=False
            list(spec.argv),
            cwd=str(spec.cwd),
            env=env,
            capture_output=capture,
            text=True,
            check=False,
            timeout=spec.timeout,
        )

    def run_bytes(
        self, spec: CommandSpec, *, stdin: bytes | None = None
    ) -> subprocess.CompletedProcess:
        """Execute ``spec`` capturing raw bytes, optionally feeding ``stdin``.

        Same safety guarantees as :meth:`run` (argv-only, shell=False, controlled
        environment).  Bytes mode is used by runtime command execution (E10-S1)
        where stdout/stderr are opaque payloads (e.g. a database dump) and an
        input stream may be piped in; nothing is decoded or printed here.
        """

        env = self._merged_env(spec.env)
        return subprocess.run(  # noqa: S603 - argv list, shell=False
            list(spec.argv),
            cwd=str(spec.cwd),
            env=env,
            input=stdin,
            capture_output=True,
            text=False,
            check=False,
            timeout=spec.timeout,
        )

    def popen(self, spec: CommandSpec, **kwargs) -> subprocess.Popen:
        """Start ``spec`` as a background process with shell=False (R7)."""

        env = self._merged_env(spec.env)
        return subprocess.Popen(  # noqa: S603 - argv list, shell=False
            list(spec.argv),
            cwd=str(spec.cwd),
            env=env,
            **kwargs,
        )

    def _merged_env(self, extra: Mapping[str, str]) -> dict[str, str]:
        # R13: start from a controlled base (allowlist of essential host
        # variables), not the full host environment, then overlay the caller's
        # explicit variables.  Callers decide what to inject; we never invent
        # product config from unrelated host variables.
        env = controlled_base_env()
        env.update(extra)
        return env


def controlled_base_env() -> dict[str, str]:
    """Return the controlled base environment for external commands (R13).

    Only the allowlisted essential variables are carried over from the host;
    everything else is intentionally dropped so it cannot leak into a child as
    product configuration (E7-S2 R13, E9-S3 INV-03).
    """

    base: dict[str, str] = {}
    for key in _BASE_ENV_ALLOWLIST:
        value = os.environ.get(key)
        if value is not None:
            base[key] = value
    return base
