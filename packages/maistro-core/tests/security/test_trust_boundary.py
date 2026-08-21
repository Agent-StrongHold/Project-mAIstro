"""Tests for trust boundary and permission system.

Evidence source: The reference implementation's trust-boundary.ts defines a permission grant
system with glob-based path matching, time-limited grants, and task spec
validation including path traversal detection and prompt stuffing limits.
"""

from __future__ import annotations

import time

from maistro.security.trust_boundary import (
    Action,
    PermissionGrant,
    TaskSpec,
    check_permission,
    create_grant_for_task,
)


class TestTaskSpecValidation:
    """Evidence: The reference implementation validates task specs at the trust boundary with
    content length limits, path traversal detection, and scope requirements."""

    def test_valid_spec(self) -> None:
        spec = TaskSpec(
            task_id="task-123",
            description="Add login endpoint",
            write_scopes=["src/**"],
            allowed_commands=["pytest"],
        )
        violations = spec.validate_spec()
        assert violations == []

    def test_missing_task_id(self) -> None:
        spec = TaskSpec(task_id="", description="test")
        violations = spec.validate_spec()
        assert any("Task ID" in v for v in violations)

    def test_description_length_limit(self) -> None:
        """Evidence: The reference implementation limits content to 50,000 chars to prevent
        prompt stuffing attacks."""
        spec = TaskSpec(task_id="t1", description="x" * 60_000)
        violations = spec.validate_spec()
        assert any("50,000" in v for v in violations)

    def test_path_traversal_dotdot(self) -> None:
        """Evidence: The reference implementation blocks '..' in write scopes to prevent
        directory traversal escapes."""
        spec = TaskSpec(
            task_id="t1",
            description="test",
            write_scopes=["../../../etc/passwd"],
        )
        violations = spec.validate_spec()
        assert any("traversal" in v.lower() for v in violations)

    def test_absolute_path_outside_workspace(self) -> None:
        """Evidence: The reference implementation blocks absolute paths that point outside
        the workspace or tmp directories."""
        spec = TaskSpec(
            task_id="t1",
            description="test",
            write_scopes=["/etc/shadow"],
        )
        violations = spec.validate_spec()
        assert any("Absolute path" in v for v in violations)

    def test_workspace_path_allowed(self) -> None:
        spec = TaskSpec(
            task_id="t1",
            description="test",
            write_scopes=["/workspace"],
        )
        violations = spec.validate_spec()
        assert violations == []


class TestPermissionGrants:
    """Evidence: The reference implementation's permission grant system uses glob patterns,
    time-limited expiry, and per-action checks."""

    def test_read_permission_granted(self) -> None:
        grant = PermissionGrant(
            grantee="coder",
            read_paths=["/workspace/**"],
            expires_at=time.time() + 3600,
        )
        assert check_permission(grant, Action.READ, path="/workspace/src/main.py")

    def test_read_permission_denied(self) -> None:
        grant = PermissionGrant(
            grantee="coder",
            read_paths=["/workspace/src/**"],
            expires_at=time.time() + 3600,
        )
        assert not check_permission(grant, Action.READ, path="/etc/passwd")

    def test_write_permission_granted(self) -> None:
        grant = PermissionGrant(
            grantee="coder",
            write_paths=["/workspace/**"],
            expires_at=time.time() + 3600,
        )
        assert check_permission(grant, Action.WRITE, path="/workspace/src/new_file.py")

    def test_write_permission_denied(self) -> None:
        grant = PermissionGrant(
            grantee="coder",
            write_paths=["/workspace/src/**"],
            expires_at=time.time() + 3600,
        )
        assert not check_permission(grant, Action.WRITE, path="/workspace/config/secret.env")

    def test_expired_grant(self) -> None:
        """Evidence: The reference implementation grants have expiry times. Expired grants
        must return False regardless of scope match."""
        grant = PermissionGrant(
            grantee="coder",
            read_paths=["**"],
            expires_at=time.time() - 1,  # Already expired
        )
        assert not check_permission(grant, Action.READ, path="/workspace/anything")

    def test_execute_permission(self) -> None:
        grant = PermissionGrant(
            grantee="coder",
            can_execute=True,
            allowed_commands=[r"^pytest\b"],
            expires_at=time.time() + 3600,
        )
        assert check_permission(grant, Action.EXECUTE, command="pytest tests/")
        assert not check_permission(grant, Action.EXECUTE, command="rm -rf /")

    def test_execute_disabled(self) -> None:
        grant = PermissionGrant(
            grantee="reviewer",
            can_execute=False,
            expires_at=time.time() + 3600,
        )
        assert not check_permission(grant, Action.EXECUTE, command="pytest tests/")

    def test_grant_id_format(self) -> None:
        """Evidence: The reference implementation uses grant-{timestamp}-{secureId(6)} format."""
        grant = PermissionGrant(grantee="test", expires_at=time.time() + 60)
        assert grant.grant_id.startswith("grant-")
        parts = grant.grant_id.split("-")
        assert len(parts) >= 3


class TestCreateGrantForTask:
    """Test the convenience function for creating standard task grants."""

    def test_standard_grant(self) -> None:
        grant = create_grant_for_task("coder", "/workspace/myrepo")
        assert grant.grantee == "coder"
        assert grant.can_execute is True
        assert len(grant.read_paths) > 0
        assert len(grant.write_paths) > 0
        assert grant.expires_at > time.time()

    def test_grant_allows_workspace_access(self) -> None:
        grant = create_grant_for_task("coder", "/workspace/myrepo")
        assert check_permission(grant, Action.READ, path="/workspace/myrepo/src/main.py")
        assert check_permission(grant, Action.WRITE, path="/workspace/myrepo/src/main.py")

    def test_grant_allows_safe_commands(self) -> None:
        grant = create_grant_for_task("coder", "/workspace/myrepo")
        assert check_permission(grant, Action.EXECUTE, command="pytest tests/")
        assert check_permission(grant, Action.EXECUTE, command="ruff check src/")
        assert check_permission(grant, Action.EXECUTE, command="git status")
