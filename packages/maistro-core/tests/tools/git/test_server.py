"""Tests for maistro.tools.git.server — git/GitHub MCP tool surface."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from maistro.tools.git import server
from maistro.tools.git.server import (
    _git,
    _parse_log_lines,
    _pr_cache_key,
    git_branch,
    git_clone,
    git_commit,
    git_diff,
    git_log,
    git_push,
    git_status,
    github_create_pr,
    github_get_pr,
    github_list_issues,
)


class _FakeProc:
    def __init__(self, stdout: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""


@pytest.fixture(autouse=True)
def _clear_pr_cache() -> None:
    server._pr_cache.clear()
    yield
    server._pr_cache.clear()


class TestPrCacheKey:
    def test_deterministic(self) -> None:
        a = _pr_cache_key("org/repo", "b", "t", "body", "main")
        b = _pr_cache_key("org/repo", "b", "t", "body", "main")
        assert a == b

    def test_differs_on_any_arg(self) -> None:
        a = _pr_cache_key("org/repo", "b", "t", "body", "main")
        b = _pr_cache_key("org/repo", "b2", "t", "body", "main")
        assert a != b


class TestGitHelper:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"clean\n", returncode=0)),
        ):
            result = await _git("/repos/ws", "status")
        assert result["success"] is True
        assert result["stdout"] == "clean\n"

    @pytest.mark.asyncio
    async def test_failure(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"err", returncode=1)),
        ):
            result = await _git("/repos/ws", "status")
        assert result["success"] is False
        assert result["error_code"] == "git_command_failed"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError),
        ):
            result = await _git("/repos/ws", "status")
        assert result["error_code"] == "git_not_found"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        with (
            patch(
                "maistro.tools.git.server.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_FakeProc()),
            ),
            patch(
                "maistro.tools.git.server.asyncio.wait_for",
                new=AsyncMock(side_effect=TimeoutError),
            ),
        ):
            result = await _git("/repos/ws", "status", timeout=5)
        assert result["error_code"] == "git_timeout"
        assert result["exit_code"] == 124


class TestParseLogLines:
    def test_parses_sha_and_message(self) -> None:
        result = _parse_log_lines("abc123 fix bug\ndef456 add feature")
        assert result == [
            {"sha": "abc123", "message": "fix bug"},
            {"sha": "def456", "message": "add feature"},
        ]

    def test_skips_empty_lines(self) -> None:
        result = _parse_log_lines("\nabc123 msg\n")
        assert result == [{"sha": "abc123", "message": "msg"}]


class TestGitClone:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"Cloned\n", returncode=0)),
        ):
            result = await git_clone("https://example.com/r.git", "/repos/dest")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_failure(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"fatal", returncode=128)),
        ):
            result = await git_clone("https://example.com/r.git", "/repos/dest")
        assert result["error_code"] == "git_clone_failed"

    @pytest.mark.asyncio
    async def test_empty_stdout_success_defaults_message(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"", returncode=0)),
        ):
            result = await git_clone("https://example.com/r.git", "/repos/dest")
        assert result["stdout"] == "Cloned"

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        with patch(
            "maistro.tools.git.server.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError),
        ):
            result = await git_clone("https://example.com/r.git", "/repos/dest")
        assert result["error_code"] == "git_not_found"

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        with (
            patch(
                "maistro.tools.git.server.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_FakeProc()),
            ),
            patch(
                "maistro.tools.git.server.asyncio.wait_for",
                new=AsyncMock(side_effect=TimeoutError),
            ),
        ):
            result = await git_clone("https://example.com/r.git", "/repos/dest", timeout=5)
        assert result["error_code"] == "git_clone_timeout"


class TestGitBranch:
    @pytest.mark.asyncio
    async def test_checkout_true_uses_checkout_b(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_branch("/repos/ws", "feature", checkout=True)
        mock_git.assert_awaited_with("/repos/ws", "checkout", "-b", "feature")

    @pytest.mark.asyncio
    async def test_checkout_false_uses_branch(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_branch("/repos/ws", "feature", checkout=False)
        mock_git.assert_awaited_with("/repos/ws", "branch", "feature")


class TestGitCommit:
    @pytest.mark.asyncio
    async def test_add_all_true_stages_and_unstages_sensitive(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_commit("/repos/ws", "msg", add_all=True)
        calls = mock_git.await_args_list
        assert calls[0].args == ("/repos/ws", "add", "-A")
        assert calls[1].args == ("/repos/ws", "reset", "HEAD", "--", ".env")
        assert calls[-1].args == ("/repos/ws", "commit", "-m", "msg")
        assert len(calls) == 1 + len(server._SENSITIVE_PATTERNS) + 1

    @pytest.mark.asyncio
    async def test_add_all_false_skips_staging(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_commit("/repos/ws", "msg", add_all=False)
        mock_git.assert_awaited_once_with("/repos/ws", "commit", "-m", "msg")


class TestGitPush:
    @pytest.mark.asyncio
    async def test_set_upstream_and_branch(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_push("/repos/ws", branch="main", set_upstream=True)
        mock_git.assert_awaited_with("/repos/ws", "push", "-u", "origin", "main")

    @pytest.mark.asyncio
    async def test_no_upstream_no_branch(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_push("/repos/ws", branch=None, set_upstream=False)
        mock_git.assert_awaited_with("/repos/ws", "push")


class TestGitDiff:
    @pytest.mark.asyncio
    async def test_staged_true(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_diff("/repos/ws", staged=True)
        mock_git.assert_awaited_with("/repos/ws", "diff", "--staged")

    @pytest.mark.asyncio
    async def test_staged_false(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_diff("/repos/ws", staged=False)
        mock_git.assert_awaited_with("/repos/ws", "diff")


class TestGitStatus:
    @pytest.mark.asyncio
    async def test_calls_status_short(self) -> None:
        with patch(
            "maistro.tools.git.server._git", new=AsyncMock(return_value={"success": True})
        ) as mock_git:
            await git_status("/repos/ws")
        mock_git.assert_awaited_with("/repos/ws", "status", "--short")


class TestGitLog:
    @pytest.mark.asyncio
    async def test_success_adds_commits(self) -> None:
        with patch(
            "maistro.tools.git.server._git",
            new=AsyncMock(return_value={"success": True, "stdout": "abc msg"}),
        ):
            result = await git_log("/repos/ws", limit=5)
        assert result["commits"] == [{"sha": "abc", "message": "msg"}]

    @pytest.mark.asyncio
    async def test_failure_no_commits_key(self) -> None:
        with patch(
            "maistro.tools.git.server._git",
            new=AsyncMock(return_value={"success": False, "stdout": ""}),
        ):
            result = await git_log("/repos/ws")
        assert "commits" not in result


class TestGithubCreatePr:
    @pytest.mark.asyncio
    async def test_cache_miss_creates_and_caches(self) -> None:
        with patch(
            "maistro.tools.git.server.create_pr",
            new=AsyncMock(
                return_value={"success": True, "output": "ok", "url": "https://x/pull/1"}
            ),
        ):
            result = await github_create_pr("org/repo", "b", "t", "body")
        assert result["success"] is True
        assert result["url"] == "https://x/pull/1"
        key = _pr_cache_key("org/repo", "b", "t", "body", "main")
        assert key in server._pr_cache

    @pytest.mark.asyncio
    async def test_cache_hit_returns_deduplicated(self) -> None:
        with patch(
            "maistro.tools.git.server.create_pr",
            new=AsyncMock(
                return_value={"success": True, "output": "ok", "url": "https://x/pull/1"}
            ),
        ) as mock_create:
            await github_create_pr("org/repo", "b", "t", "body")
            result = await github_create_pr("org/repo", "b", "t", "body")
        mock_create.assert_awaited_once()
        assert result["deduplicated"] is True

    @pytest.mark.asyncio
    async def test_cache_expired_recreates(self) -> None:
        with patch(
            "maistro.tools.git.server.create_pr",
            new=AsyncMock(
                return_value={"success": True, "output": "ok", "url": "https://x/pull/1"}
            ),
        ) as mock_create:
            await github_create_pr("org/repo", "b", "t", "body")
            key = _pr_cache_key("org/repo", "b", "t", "body", "main")
            server._pr_cache[key]["cached_at"] -= server._PR_CACHE_TTL_S + 1
            result = await github_create_pr("org/repo", "b", "t", "body")
        assert mock_create.await_count == 2
        assert "deduplicated" not in result

    @pytest.mark.asyncio
    async def test_underlying_failure_wraps_error(self) -> None:
        with patch(
            "maistro.tools.git.server.create_pr",
            new=AsyncMock(return_value={"success": False, "output": "boom", "exit_code": 1}),
        ):
            result = await github_create_pr("org/repo", "b", "t", "body")
        assert result["success"] is False
        assert result["error_code"] == "gh_pr_create_failed"


class TestGithubGetPr:
    @pytest.mark.asyncio
    async def test_success(self) -> None:
        with patch(
            "maistro.tools.git.server.get_pr",
            new=AsyncMock(return_value={"title": "t", "state": "OPEN"}),
        ):
            result = await github_get_pr("org/repo", 1)
        assert result["success"] is True
        assert result["title"] == "t"

    @pytest.mark.asyncio
    async def test_error_wraps(self) -> None:
        with patch(
            "maistro.tools.git.server.get_pr",
            new=AsyncMock(return_value={"error": "not found"}),
        ):
            result = await github_get_pr("org/repo", 1)
        assert result["error_code"] == "gh_pr_fetch_failed"


class TestGithubListIssues:
    @pytest.mark.asyncio
    async def test_with_issues(self) -> None:
        with patch(
            "maistro.tools.git.server.list_issues",
            new=AsyncMock(return_value=[{"number": 1}]),
        ):
            result = await github_list_issues("org/repo")
        assert result["stdout"] == "1 open issue(s)"
        assert result["issue_count"] == 1

    @pytest.mark.asyncio
    async def test_no_issues(self) -> None:
        with patch("maistro.tools.git.server.list_issues", new=AsyncMock(return_value=[])):
            result = await github_list_issues("org/repo")
        assert result["stdout"] == "No open issues"
        assert result["issue_count"] == 0
