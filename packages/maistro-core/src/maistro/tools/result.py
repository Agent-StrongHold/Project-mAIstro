"""Structured result types for MCP tool returns.

Replaces plain string returns so agents don't need to parse formatted strings.
"""

from __future__ import annotations

from typing import Any


def ok(stdout: str = "", exit_code: int = 0, **extra: Any) -> dict[str, Any]:
    """Build a successful tool result."""
    return {"success": True, "exit_code": exit_code, "stdout": stdout, **extra}


def fail(
    stdout: str = "",
    exit_code: int = 1,
    *,
    error_code: str = "error",
    recoverable: bool = False,
    suggested_action: str = "",
    **extra: Any,
) -> dict[str, Any]:
    """Build a failed tool result.

    error_code is machine-readable so the agent can branch without parsing
    stdout; recoverable signals whether a retry could plausibly succeed;
    suggested_action tells the agent what to do next.
    """
    return {
        "success": False,
        "exit_code": exit_code,
        "stdout": stdout,
        "error_code": error_code,
        "recoverable": recoverable,
        "suggested_action": suggested_action,
        **extra,
    }
