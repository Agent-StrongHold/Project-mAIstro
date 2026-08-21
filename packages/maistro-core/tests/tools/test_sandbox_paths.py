"""Tests for SandboxContainer path safety.

Evidence: The sandbox must prevent path traversal and absolute path injection
that could allow reading/writing files outside /workspace.
"""

from __future__ import annotations

import pytest

from maistro.tools.sandbox.docker import SandboxContainer


class TestSafePathResolution:
    """Evidence: _safe_path must block absolute paths and traversal attempts."""

    def test_relative_path_resolves_under_workspace(self) -> None:
        result = SandboxContainer._safe_path("/workspace", "src/main.py")
        assert result == "/workspace/src/main.py"

    def test_absolute_path_rejected(self) -> None:
        with pytest.raises(ValueError, match="Absolute paths"):
            SandboxContainer._safe_path("/workspace", "/etc/passwd")

    def test_traversal_rejected(self) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            SandboxContainer._safe_path("/workspace", "../../etc/passwd")

    def test_traversal_in_middle_rejected(self) -> None:
        with pytest.raises(ValueError, match="Path traversal"):
            SandboxContainer._safe_path("/workspace", "src/../../etc/passwd")

    def test_normalized_dot_path(self) -> None:
        result = SandboxContainer._safe_path("/workspace", "./src/main.py")
        assert result == "/workspace/src/main.py"

    def test_simple_filename(self) -> None:
        result = SandboxContainer._safe_path("/workspace", "README.md")
        assert result == "/workspace/README.md"
