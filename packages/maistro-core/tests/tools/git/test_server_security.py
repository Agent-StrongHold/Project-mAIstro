"""Security tests for git MCP workspace boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.tools.git.server import git_clone, git_status


@pytest.mark.parametrize("workspace", ["/etc", "/root/.ssh", "/tmp/maistro-workspace-evil/repo"])
async def test_git_status_rejects_disallowed_workspace_before_git(
    monkeypatch: pytest.MonkeyPatch, workspace: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git subprocess should not be created for blocked workspaces")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_status(workspace)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"


async def test_git_status_allows_workspace_under_allowed_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    workspace = Path("/tmp/maistro-workspace/git-server-test")
    workspace.mkdir(parents=True, exist_ok=True)

    class _Proc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, None]:
            return b"", None

    async def fake_exec(*args: object, **kwargs: object) -> _Proc:
        assert args[:3] == ("git", "-C", str(workspace.resolve()))
        return _Proc()

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fake_exec)

    result = await git_status(str(workspace))

    assert result["success"] is True


@pytest.mark.parametrize("dest", ["/etc/repo", "/tmp/maistro-workspace-evil/repo"])
async def test_git_clone_rejects_disallowed_dest_before_git(
    monkeypatch: pytest.MonkeyPatch, dest: str
) -> None:
    async def fail_exec(
        *args: object, **kwargs: object
    ) -> object:  # pragma: no cover - must not run
        raise AssertionError("git clone should not be created for blocked destinations")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_clone("https://example.com/repo.git", dest)

    assert result["success"] is False
    assert result["error_code"] == "blocked_workspace"
