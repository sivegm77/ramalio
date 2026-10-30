"""ramalio package.

``__version__`` is the single source of truth for the product version (E9-S1 R4);
``pyproject.toml`` derives it dynamically.  ``SUPPORTED_CONFIG_SCHEMA`` is the
configuration schema version this CLI understands; a project may declare
``[meta].schema_version`` and a newer-than-supported value fails closed
(E9-S1 R11/R12/INV-05).
"""

__version__ = "0.1.0"

# Configuration schema version supported by this CLI (E9-S1 R11).
SUPPORTED_CONFIG_SCHEMA = 1

__all__ = ["__version__", "SUPPORTED_CONFIG_SCHEMA"]
