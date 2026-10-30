"""Reusable conformance harness (E7-S3 R1).

Creates temporary real Git projects with their own configuration, runs the CLI,
and inspects Git/filesystem.  It is product-generic: no SiVale/Laravel/Kiro
naming is baked in (R18).  External tools (tmux/zrok/docker) are never required;
optional integration profiles live elsewhere (R4/R20).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path

from ramalio.cli import main
from ramalio.git.repository import GitRepository


# --- project profiles (R2) -------------------------------------------------

# Profile 1: Git-only, no capabilities.
PROFILE_GIT_ONLY = """
[project]
name = "conformance"
base_branch = "main"

[target]
regex = "^[a-z0-9-]+$"
example = "my-feature"
case_sensitive = false

[worktree]
directory = ".local-wt"
pattern = "{target}"

[branch]
pattern = "{target}"
"""

# Profile 2: Git + a managed process capability.
PROFILE_PROCESSES = PROFILE_GIT_ONLY + """
[capabilities.processes]
enabled = true

[[capabilities.processes.items]]
name = "worker"
command = ["sleep", "30"]
start_on_start = true
stop_on_stop = true
stop_on_destroy = true
"""

# Profile 3: Runtime (none driver) + ports + tunnel (simulated provider).
PROFILE_RUNTIME_PORTS_TUNNEL = PROFILE_GIT_ONLY + """
[ports]
enabled = true
start = 8600
size = 10

[capabilities.runtime]
driver = "none"

[capabilities.tunnel]
enabled = true
provider = "zrok"
"""


@dataclass(slots=True)
class CliResult:
    code: int
    stdout: str
    stderr: str


@dataclass(slots=True)
class ConformanceProject:
    """A temporary, real Git project usable by conformance tests."""

    root: Path
    _env: dict = field(default_factory=dict)

    def git(self, *args: str, cwd: Path | None = None) -> str:
        completed = subprocess.run(
            ["git", "-C", str(cwd or self.root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout

    def run_cli(self, *args: str) -> CliResult:
        """Run the CLI with cwd set to the project root."""

        import os

        stdout, stderr = StringIO(), StringIO()
        prev = os.getcwd()
        os.chdir(self.root)
        try:
            code = main(list(args), stdout=stdout, stderr=stderr)
        finally:
            os.chdir(prev)
        return CliResult(code=code, stdout=stdout.getvalue(), stderr=stderr.getvalue())

    def repo(self) -> GitRepository:
        return GitRepository.from_root(self.root)

    def worktree_path(self, target: str) -> Path:
        return (self.root / ".local-wt" / target).resolve()


def make_project(tmp_path: Path, profile: str) -> ConformanceProject:
    """Create a real Git repo with one commit on main and the given profile."""

    root = tmp_path / "project"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    env_args = {
        "GIT_AUTHOR_NAME": "conf",
        "GIT_AUTHOR_EMAIL": "conf@example.com",
        "GIT_COMMITTER_NAME": "conf",
        "GIT_COMMITTER_EMAIL": "conf@example.com",
    }
    import os

    for key, value in env_args.items():
        os.environ.setdefault(key, value)
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
    (root / ".ramalio.toml").write_text(profile, encoding="utf-8")
    return ConformanceProject(root=root)
