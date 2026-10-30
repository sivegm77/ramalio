"""Centralized product defaults (R9).

Defaults are limited to universal, safe values.  They must not encode any
specific stack (no PHP, Node, Docker, tmux, Kiro...), must not invent secrets,
and must never enable external capabilities by default (INV-02, INV-09, R9).

Defaults are expressed as a plain, TOML-shaped mapping so the loader can merge
them with personal and project configuration through a single, testable path.
The mapping is deliberately observable so tests can assert on it directly.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# The default configuration tree.  Only universal, stack-agnostic values live
# here.  ``project.name`` has no safe universal default and stays required.
_DEFAULTS: dict[str, Any] = {
    "project": {
        # "main" is the modern, stack-neutral default base branch.
        "base_branch": "main",
    },
    "target": {
        "case_sensitive": False,
        "normalization": {
            "trim": True,
            "lowercase_slug": True,
            "replace_spaces": "-",
            "collapse_dashes": True,
            "slug_separator": "-",
            "preserve_prefix_segments": 0,
        },
    },
    "worktree": {
        "directory": ".local-wt",
        "pattern": "{target}",
    },
    "branch": {
        "pattern": "{target}",
        # Conservative default: destroy preserves the branch (E2-S3 R10).
        "delete_on_destroy": False,
    },
    # No capabilities or integrations are enabled by default (INV-09).
    "capabilities": {},
    "integrations": {},
}


def product_defaults() -> dict[str, Any]:
    """Return a deep copy of the product defaults.

    A copy is returned so callers can merge/override without mutating the
    canonical defaults, keeping resolution deterministic (INV-07).
    """

    return deepcopy(_DEFAULTS)
