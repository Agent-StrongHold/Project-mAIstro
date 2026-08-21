"""Dangerous command and tool detection.

Identifies commands and tool invocations that could be destructive
or security-sensitive. Pattern data lives in security/patterns.py.
"""

from __future__ import annotations

from maistro.security.patterns import (
    BLOCKED_HOST_PATHS,
    DANGEROUS_COMMAND_PATTERNS,
    DANGEROUS_TOOL_NAMES,
)


def is_dangerous_command(command: str) -> list[str]:
    """Check if a command matches any dangerous patterns.

    Returns list of matched pattern descriptions. Empty = safe.
    """
    return [p.pattern for p in DANGEROUS_COMMAND_PATTERNS if p.search(command)]


def is_dangerous_tool(tool_name: str) -> bool:
    """Check if a tool name is in the dangerous tools set."""
    return tool_name.lower() in DANGEROUS_TOOL_NAMES


def is_blocked_path(path: str) -> bool:
    """Check if a path is in the blocked host paths set."""
    normalized = path.rstrip("/")
    return any(
        normalized == blocked or normalized.startswith(f"{blocked}/")
        for blocked in BLOCKED_HOST_PATHS
    )
