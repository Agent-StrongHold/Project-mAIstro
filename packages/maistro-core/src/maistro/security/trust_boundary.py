"""Trust boundary and per-agent permission system.

Implements permission grants that control what agents can read, write,
and execute. Ported from the gateway product TypeScript trust-boundary module.
"""

from __future__ import annotations

import fnmatch
import time
from enum import StrEnum

from pydantic import BaseModel, Field

from maistro.constants import PERMISSION_MAX_INPUT, PERMISSION_TTL
from maistro.security.secure_random import secure_id


class Action(StrEnum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class PermissionGrant(BaseModel):
    """A time-limited permission grant for an agent."""

    grant_id: str = Field(default_factory=lambda: f"grant-{int(time.time())}-{secure_id(6)}")
    grantee: str  # Agent role or ID
    read_paths: list[str] = Field(default_factory=list)  # Glob patterns
    write_paths: list[str] = Field(default_factory=list)  # Glob patterns
    can_execute: bool = False
    allowed_commands: list[str] = Field(default_factory=list)  # Regex patterns
    expires_at: float = Field(default_factory=lambda: time.time() + PERMISSION_TTL)


class TaskSpec(BaseModel):
    """Validated task specification crossing the trust boundary."""

    task_id: str
    description: str
    write_scopes: list[str] = Field(default_factory=list)
    allowed_commands: list[str] = Field(default_factory=list)

    def validate_spec(self) -> list[str]:
        """Validate the task spec for security issues. Returns list of violations."""
        violations: list[str] = []

        if not self.task_id:
            violations.append("Task ID is required")

        if len(self.description) > PERMISSION_MAX_INPUT:
            violations.append("Description exceeds 50,000 char limit (prompt stuffing prevention)")

        # Check for path traversal in write scopes
        for scope in self.write_scopes:
            if ".." in scope:
                violations.append(f"Path traversal detected in write scope: {scope}")
            # The literal "/tmp" here is the RIGHT-HAND side of a not-equal
            # check, i.e. the security gate REJECTS arbitrary /tmp/whatever
            # paths; this is the negative case. Not a tmpfile usage.
            if scope.startswith("/") and scope not in ("/workspace", "/tmp"):  # nosec B108
                violations.append(f"Absolute path outside workspace: {scope}")

        return violations


def _matches_glob(path: str, patterns: list[str]) -> bool:
    """Check if a path matches any of the glob patterns."""
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def check_permission(
    grant: PermissionGrant,
    action: Action,
    path: str | None = None,
    command: str | None = None,
) -> bool:
    """Check if a permission grant allows the requested action.

    Args:
        grant: The permission grant to check
        action: The action being attempted
        path: File path (for read/write actions)
        command: Command string (for execute actions)
    """
    # Check expiry
    if time.time() > grant.expires_at:
        return False

    if action == Action.READ and path:
        return _matches_glob(path, grant.read_paths)

    if action == Action.WRITE and path:
        return _matches_glob(path, grant.write_paths)

    if action == Action.EXECUTE:
        if not grant.can_execute:
            return False
        if command and grant.allowed_commands:
            import re

            return any(re.search(pattern, command) for pattern in grant.allowed_commands)
        return grant.can_execute

    return False


def create_grant_for_task(
    grantee: str,
    workspace: str,
    ttl_seconds: int = PERMISSION_TTL,
    can_execute: bool = True,
) -> PermissionGrant:
    """Create a standard permission grant for a task execution."""
    return PermissionGrant(
        grantee=grantee,
        read_paths=[f"{workspace}/**", "/workspace/**"],
        write_paths=[f"{workspace}/**", "/workspace/**"],
        can_execute=can_execute,
        allowed_commands=[r"^(python|pytest|ruff|mypy|git|npm|pip|uv)\b"],
        expires_at=time.time() + ttl_seconds,
    )
