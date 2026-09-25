"""Tests for sandbox path safety.

Evidence: the sandbox must prevent path traversal and absolute path injection
that could allow reading/writing files outside the workspace.

The guard used to live in the legacy launcher's ``SandboxContainer._safe_path``
(#18 retired that second launcher). Containment is now enforced once, in
``maistro.sandbox.paths`` — ``_relative_parts`` parses the guest path for every
backend, and ``read_beneath``/``write_beneath`` open it relative to the
workspace root without following symlinks. These tests pin the same properties
against the canonical layer, which is where the guarantee now lives.
"""

from __future__ import annotations

import pytest

from maistro.sandbox.paths import _relative_parts, read_beneath, write_beneath


class TestGuestPathContainment:
    """Evidence: _relative_parts must block absolute paths and traversal attempts."""

    def test_relative_path_resolves_under_workspace(self) -> None:
        assert _relative_parts("src/main.py") == ("src", "main.py")

    def test_absolute_path_outside_mount_rejected(self) -> None:
        with pytest.raises(ValueError, match="outside sandbox mount"):
            _relative_parts("/etc/passwd")

    def test_absolute_path_under_mount_accepted(self) -> None:
        # Guest-absolute is fine when it stays inside the sandbox mount.
        assert _relative_parts("/work/src/main.py") == ("src", "main.py")

    def test_traversal_rejected(self) -> None:
        with pytest.raises(ValueError, match="escapes sandbox root"):
            _relative_parts("../../etc/passwd")

    def test_traversal_in_middle_rejected(self) -> None:
        with pytest.raises(ValueError, match="escapes sandbox root"):
            _relative_parts("src/../../etc/passwd")

    def test_normalized_dot_path(self) -> None:
        assert _relative_parts("./src/main.py") == ("src", "main.py")

    def test_simple_filename(self) -> None:
        assert _relative_parts("README.md") == ("README.md",)


class TestBeneathSemantics:
    """Evidence: read/write beneath the root honor the same containment."""

    def test_write_then_read_roundtrip(self, tmp_path) -> None:
        write_beneath(tmp_path, "src/main.py", b"print('hi')\n")
        assert read_beneath(tmp_path, "src/main.py") == b"print('hi')\n"

    def test_write_refuses_traversal(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="escapes sandbox root"):
            write_beneath(tmp_path, "../escape.txt", b"no")

    def test_read_refuses_symlink_escape(self, tmp_path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("secret")
        (tmp_path / "link.txt").symlink_to(outside)
        with pytest.raises(OSError):
            read_beneath(tmp_path, "link.txt")
