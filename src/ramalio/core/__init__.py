"""Core contracts shared by the ramalio CLI and future lifecycle code."""

from .errors import (
    ConfigurationError,
    NotInGitRepositoryError,
    OperationError,
    ProjectConfigInvalidError,
    ProjectConfigNotFoundError,
    ProjectConfigParseError,
    RamalioError,
    SafetyError,
    StateError,
    TargetExampleInvalidError,
    TargetInvalidError,
    TargetRegexInvalidError,
    TargetTooLongError,
    UsageError,
)
from .result import CommandResult, ExitCode
from .target import MAX_TARGET_LENGTH, Target, TargetPolicy, TargetValidator

__all__ = [
    "CommandResult",
    "ConfigurationError",
    "ExitCode",
    "MAX_TARGET_LENGTH",
    "NotInGitRepositoryError",
    "OperationError",
    "ProjectConfigInvalidError",
    "ProjectConfigNotFoundError",
    "ProjectConfigParseError",
    "RamalioError",
    "SafetyError",
    "StateError",
    "Target",
    "TargetExampleInvalidError",
    "TargetInvalidError",
    "TargetPolicy",
    "TargetRegexInvalidError",
    "TargetTooLongError",
    "TargetValidator",
    "UsageError",
]
