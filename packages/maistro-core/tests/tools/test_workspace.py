"""Tests for workspace path validation.

Evidence: Sandbox containers must only mount from allowed host prefixes
to prevent arbitrary filesystem access. This mirrors the reference gateway
validate-sandbox-security.ts path validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.tools.sandbox.workspace import ensure_workspace, validate_workspace_path


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


class TestAdversarialBypassAttempts:
    """Guardrail-probe-style fixed payloads against validate_workspace_path.

    Each case targets a specific bypass technique: sibling-directory prefix
    confusion, symlink escape, null-byte injection, and Unicode lookalikes
    for '.' / '/' that must NOT be treated as traversal.
    """

    def test_sibling_directory_prefix_confusion_blocked(self, tmp_path: Path) -> None:
        """ "/tmp/maistro-workspace-evil" merely shares a string prefix with
        the allowed "/tmp/maistro-workspace" — it is a different directory
        and must not be let through by a naive str.startswith() check."""
        sibling = Path("/tmp/maistro-workspace-evil")
        sibling.mkdir(exist_ok=True)
        with pytest.raises(ValueError, match="not in an allowed location"):
            validate_workspace_path(str(sibling / "secret"))

    def test_symlink_escape_blocked(self) -> None:
        """A symlink planted inside the allowed tree that points outside it
        must not grant access to the target — resolve() follows the link
        before the prefix check runs."""
        link = Path("/tmp/maistro-workspace/escape-link")
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to("/etc")
        try:
            with pytest.raises(ValueError, match="not in an allowed location"):
                validate_workspace_path(str(link / "passwd"))
        finally:
            link.unlink()

    def test_null_byte_injection_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_workspace_path("/tmp/maistro-workspace/foo\x00/etc/passwd")

    @pytest.mark.parametrize(
        "lookalike",
        [
            "．．",  # noqa: RUF001 -- fullwidth full stop, not ASCII '.'
            "․․",  # noqa: RUF001 -- one dot leader, not ASCII '.'
        ],
        ids=["fullwidth-dot", "dot-leader"],
    )
    def test_unicode_dot_lookalikes_are_not_traversal(self, lookalike: str) -> None:
        """Unicode characters that visually resemble '..' are ordinary
        filename bytes to the filesystem, not traversal — they must stay
        within the workspace, not escape it."""
        path = validate_workspace_path(f"/tmp/maistro-workspace/{lookalike}/etc/passwd")
        assert str(path).startswith(_resolved_tmp_workspace_root())

    def test_allowed_root_itself(self) -> None:
        """The prefix directory itself (no trailing component) is allowed,
        symmetric with how "/repos" without a trailing slash is allowed."""
        path = validate_workspace_path("/tmp/maistro-workspace")
        assert str(path) == _resolved_tmp_workspace_root()

    def test_repos_root_itself_allowed(self) -> None:
        path = validate_workspace_path("/repos")
        assert str(path) == "/repos"


class TestEnsureWorkspace:
    """Evidence: ensure_workspace validates then creates the directory."""

    def test_creates_directory_when_missing(self, tmp_path: Path) -> None:
        target = f"/tmp/maistro-workspace/{tmp_path.name}/nested"
        resolved = ensure_workspace(target)
        assert resolved.is_dir()

    def test_idempotent_when_directory_exists(self, tmp_path: Path) -> None:
        target = f"/tmp/maistro-workspace/{tmp_path.name}/again"
        ensure_workspace(target)
        resolved = ensure_workspace(target)
        assert resolved.is_dir()

    def test_raises_for_disallowed_path(self) -> None:
        with pytest.raises(ValueError, match="not in an allowed location"):
            ensure_workspace("/etc/maistro-workspace")


class TestPlatformTempDirAllowlist:
    """Evidence: maistro_rsi.runner.DEFAULT_WORKSPACE_ROOT is built from
    tempfile.gettempdir() (not a hardcoded /tmp literal) so it honors
    $TMPDIR; the allowlist must actually cover that default or workspace
    creation fails validation on any host where $TMPDIR isn't /tmp."""

    def test_platform_tempdir_workspace_is_allowed(self) -> None:
        import tempfile

        from maistro.tools.sandbox.workspace import ALLOWED_HOST_ROOTS

        expected = Path(tempfile.gettempdir()) / "maistro-workspace"
        assert expected in ALLOWED_HOST_ROOTS

    def test_platform_tempdir_workspace_passes_validation(self) -> None:
        import tempfile

        target = str(Path(tempfile.gettempdir()) / "maistro-workspace" / "rsi" / "run1")
        resolved = validate_workspace_path(target)
        assert str(resolved).endswith("maistro-workspace/rsi/run1")
