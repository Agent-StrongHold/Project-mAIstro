"""Security tests for git MCP workspace boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.tools.git.server import (
    git_branch,
    git_clone,
    git_status,
    github_create_pr,
    github_get_pr,
    github_list_issues,
)


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


async def test_git_branch_rejects_option_injection_before_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(*args: object, **kwargs: object) -> object:
        raise AssertionError("git subprocess should not be created for invalid refs")

    monkeypatch.setattr("maistro.tools.git.server.asyncio.create_subprocess_exec", fail_exec)

    result = await git_branch("/tmp/maistro-workspace/repo", "--upload-pack=evil")

    assert result["success"] is False
    assert result["error_code"] == "invalid_branch_name"


async def test_github_create_pr_rejects_invalid_repo_before_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(*args: object, **kwargs: object) -> object:
        raise AssertionError("gh subprocess should not be created for invalid repos")

    monkeypatch.setattr("maistro.tools.git.github._run_gh", fail_exec)

    result = await github_create_pr("--repo", "feature", "title", "body")

    assert result["success"] is False
    assert result["error_code"] == "invalid_repository"


async def test_github_create_pr_rejects_invalid_branch_and_base_before_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(*args: object, **kwargs: object) -> object:
        raise AssertionError("gh subprocess should not be created for invalid refs")

    monkeypatch.setattr("maistro.tools.git.github._run_gh", fail_exec)

    bad_branch = await github_create_pr("owner/repo", "--evil", "title", "body")
    assert bad_branch["success"] is False
    assert bad_branch["error_code"] == "invalid_branch_name"

    bad_base = await github_create_pr(
        "owner/repo", "feature", "title", "body", "--upload-pack=evil"
    )
    assert bad_base["success"] is False
    assert bad_base["error_code"] == "invalid_base_ref"


async def test_github_get_pr_rejects_invalid_repo_before_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(*args: object, **kwargs: object) -> object:
        raise AssertionError("gh subprocess should not be created for invalid repos")

    monkeypatch.setattr("maistro.tools.git.server.get_pr", fail_exec)

    result = await github_get_pr("owner; rm -rf /", 1)

    assert result["success"] is False
    assert result["error_code"] == "invalid_repository"


async def test_github_list_issues_rejects_invalid_repo_before_gh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_exec(*args: object, **kwargs: object) -> object:
        raise AssertionError("gh subprocess should not be created for invalid repos")

    monkeypatch.setattr("maistro.tools.git.server.list_issues", fail_exec)

    result = await github_list_issues("-x/y", 5)

    assert result["success"] is False
    assert result["error_code"] == "invalid_repository"


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
