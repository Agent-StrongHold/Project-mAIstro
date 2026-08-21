"""Typed error hierarchy for the builders sandbox (SPEC-200)."""

from __future__ import annotations


class BuildersSandboxError(Exception):
    """Base for all sandbox errors."""


class SandboxEscapeError(BuildersSandboxError):
    """A path resolved outside the sandbox root."""


class BlockedCommandError(BuildersSandboxError):
    """A shell command matched the blocklist."""


class CommandTimeoutError(BuildersSandboxError):
    """A shell command exceeded its time limit."""


class OutputTruncatedWarning(UserWarning):
    """Command output exceeded the size cap and was truncated."""


class WorkspaceTeardownError(BuildersSandboxError):
    """Worktree cleanup failed (non-fatal; logs and continues)."""
