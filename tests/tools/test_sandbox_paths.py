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


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "src/../../etc/passwd"])
def test_sandbox_grep_rejects_path_traversal_before_container(
    monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    from maistro.tools.sandbox import server as sandbox_server

    async def fail_get_or_create(workspace: str):  # pragma: no cover - must not be called
        raise AssertionError("container should not be created for blocked grep path")

    monkeypatch.setattr(sandbox_server, "_get_or_create", fail_get_or_create)

    import asyncio

    result = asyncio.run(sandbox_server.sandbox_grep("/tmp/maistro-workspace/repo", "root", path))
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"


@pytest.mark.parametrize("pattern", ["../../*.py", "/etc/*", "src/../../*.py"])
def test_sandbox_glob_rejects_path_traversal_before_container(
    monkeypatch: pytest.MonkeyPatch, pattern: str
) -> None:
    from maistro.tools.sandbox import server as sandbox_server

    async def fail_get_or_create(workspace: str):  # pragma: no cover - must not be called
        raise AssertionError("container should not be created for blocked glob pattern")

    monkeypatch.setattr(sandbox_server, "_get_or_create", fail_get_or_create)

    import asyncio

    result = asyncio.run(sandbox_server.sandbox_glob("/tmp/maistro-workspace/repo", pattern))
    assert result["success"] is False
    assert result["error_code"] == "blocked_path"
