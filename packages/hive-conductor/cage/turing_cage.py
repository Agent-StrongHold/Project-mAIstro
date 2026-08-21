"""Turing Cage — hard enforcement layer.

Three checkpoints, all deterministic (no LLM calls):
  1. check_pr      — reject PRs touching protected paths
  2. check_output  — sanitize agent outputs (no secrets, no escalation language)
  3. check_tool_call — block disallowed tools, enforce tier permissions

Every check returns a CageVerdict. If blocked=True, the action is halted.
The cage NEVER raises exceptions — it returns structured verdicts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from cage.immutable_paths import is_immutable
from cage.memory_rules import MemoryRules
from cage.permission_boundary import PermissionBoundary, Tier


@dataclass(frozen=True)
class CageVerdict:
    blocked: bool
    reason: str
    checkpoint: str
    details: dict[str, Any] = field(default_factory=dict)


# Patterns that indicate escalation attempts in output text
_ESCALATION_PATTERNS = [
    re.compile(r"(?i)ignore\s+(previous|prior|all)\s+(instructions?|rules?|constraints?)"),
    re.compile(r"(?i)you\s+are\s+now\s+(admin|root|unrestricted)"),
    re.compile(r"(?i)override\s+(safety|cage|permission|tier)"),
    re.compile(r"(?i)grant\s+(me|yourself|this\s+agent)\s+(admin|elevated|higher)"),
    re.compile(r"(?i)disable\s+(cage|safety|guard|filter)"),
]

# Patterns that look like leaked secrets
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|credential)\s*[:=]\s*\S{8,}"),
    re.compile(r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----"),
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9\-_.]{20,}"),
]

# Tools that are never allowed regardless of tier
_BLOCKED_TOOLS = frozenset(
    [
        "shell_exec_root",
        "modify_cage",
        "modify_eval",
        "delete_all_memory",
        "escalate_tier",
        "disable_logging",
        "raw_sql_exec",
    ]
)


class TuringCage:
    """Deterministic enforcement — no LLM calls, no network, pure logic."""

    def __init__(self) -> None:
        self.memory_rules = MemoryRules()
        self.permission_boundary = PermissionBoundary()

    def check_pr(self, changed_files: list[str]) -> CageVerdict:
        """Block PRs that touch immutable paths."""
        violations = [f for f in changed_files if is_immutable(f)]
        if violations:
            return CageVerdict(
                blocked=True,
                reason=f"PR touches immutable paths: {violations}",
                checkpoint="check_pr",
                details={"immutable_files": violations},
            )
        return CageVerdict(blocked=False, reason="", checkpoint="check_pr")

    def check_output(self, text: str) -> CageVerdict:
        """Sanitize agent output — block escalation language and leaked secrets."""
        for pat in _ESCALATION_PATTERNS:
            m = pat.search(text)
            if m:
                return CageVerdict(
                    blocked=True,
                    reason=f"Output contains escalation attempt: '{m.group()}'",
                    checkpoint="check_output",
                    details={"match": m.group(), "pattern": pat.pattern},
                )
        for pat in _SECRET_PATTERNS:
            m = pat.search(text)
            if m:
                return CageVerdict(
                    blocked=True,
                    reason="Output contains potential secret/credential leak",
                    checkpoint="check_output",
                    details={"pattern": pat.pattern},
                )
        return CageVerdict(blocked=False, reason="", checkpoint="check_output")

    def check_tool_call(
        self, tool_name: str, agent_tier: Tier, args: dict[str, Any] | None = None
    ) -> CageVerdict:
        """Block disallowed tools and enforce tier permissions."""
        if tool_name in _BLOCKED_TOOLS:
            return CageVerdict(
                blocked=True,
                reason=f"Tool '{tool_name}' is permanently blocked",
                checkpoint="check_tool_call",
                details={"tool": tool_name},
            )
        if not self.permission_boundary.can_call_tool(agent_tier):
            return CageVerdict(
                blocked=True,
                reason=f"Tier {agent_tier.name} cannot call tools",
                checkpoint="check_tool_call",
                details={"tier": agent_tier.name, "tool": tool_name},
            )
        # Check if tool tries to write to immutable paths
        if args:
            path = args.get("path") or args.get("file") or args.get("target", "")
            if path and is_immutable(path):
                return CageVerdict(
                    blocked=True,
                    reason=f"Tool targets immutable path: {path}",
                    checkpoint="check_tool_call",
                    details={"tool": tool_name, "path": path},
                )
        return CageVerdict(blocked=False, reason="", checkpoint="check_tool_call")
