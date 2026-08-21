"""Tests for workspace path validation.

Evidence: Sandbox containers must only mount from allowed host prefixes
to prevent arbitrary filesystem access. This mirrors the reference gateway
validate-sandbox-security.ts path validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.tools.sandbox.workspace import validate_workspace_path


def _resolved_tmp_workspace_root() -> str:
    """Host-specific real path for the tmp workspace mount (macOS uses /private/tmp)."""
    return str(Path("/tmp/maistro-workspace").resolve())


class TestWorkspaceValidation:
    """Evidence: Only /tmp/maistro-workspace and /repos/ prefixes are
    allowed for container mounts."""

    def test_allowed_tmp_path(self) -> None:
        path = validate_workspace_path("/tmp/maistro-workspace/myrepo")
        assert str(path).startswith(_resolved_tmp_workspace_root())

    def test_allowed_repos_path(self) -> None:
        path = validate_workspace_path("/repos/my-org/my-repo")
        assert str(path).startswith("/repos")

    @pytest.mark.parametrize(
        "path",
        [
            "/tmp/maistro-workspace-evil",
            "/tmp/maistro-workspace_evil/repo",
            "/private/tmp/maistro-workspace-evil",
            "/repos_evil/project",
            "/repos2/project",
        ],
    )
    def test_blocked_prefix_sibling_path(self, path: str) -> None:
        """Prefix lookalikes must not pass the workspace allowlist."""
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path(path)

    def test_blocked_etc(self) -> None:
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path("/etc")

    def test_blocked_root(self) -> None:
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path("/root/.ssh")

    def test_blocked_arbitrary(self) -> None:
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path("/home/user/malicious")

    def test_blocked_var_run_docker(self) -> None:
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path("/var/run/docker.sock")


class TestPathTraversal:
    """Evidence: Path traversal attacks must be blocked even when they start
    with an allowed prefix. Path.resolve() collapses '..' components."""

    def test_traversal_from_allowed_prefix(self) -> None:
        """Traversal that starts with allowed prefix but escapes."""
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path("/tmp/maistro-workspace/../../../etc/passwd")

    def test_double_dot_relative(self) -> None:
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path("../../etc/passwd")

    def test_resolved_path_stays_within_prefix(self) -> None:
        """Traversal within the allowed tree is fine — resolve() normalizes it."""
        path = validate_workspace_path("/tmp/maistro-workspace/a/../b")
        assert str(path).startswith(_resolved_tmp_workspace_root())
        # '..' was resolved, so 'a' is gone
        assert "/a/" not in str(path)
