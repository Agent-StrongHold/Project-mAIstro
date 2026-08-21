"""Tests for maistro.tools.git.github — gh CLI wrapper + agent-sized projections."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from maistro.tools.git.github import (
    _MAX_ISSUE_BODY,
    _MAX_PR_BODY,
    _MAX_REVIEW_BODY,
    _project_issue,
    _project_pr,
    _run_gh,
    create_pr,
    get_pr,
    list_issues,
)


class _FakeProc:
    def __init__(self, stdout: bytes = b"", returncode: int = 0) -> None:
        self._stdout = stdout
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self._stdout, b""


class TestRunGh:
    @pytest.mark.asyncio
    async def test_success_returns_exit_code_and_output(self) -> None:
        with patch(
            "maistro.tools.git.github.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"ok\n", returncode=0)),
        ):
            code, output = await _run_gh("pr", "list")
        assert code == 0
        assert output == "ok\n"

    @pytest.mark.asyncio
    async def test_nonzero_returncode_defaults_to_zero_when_none(self) -> None:
        with patch(
            "maistro.tools.git.github.asyncio.create_subprocess_exec",
            new=AsyncMock(return_value=_FakeProc(stdout=b"", returncode=None)),
        ):
            code, _ = await _run_gh("pr", "list")
        assert code == 0

    @pytest.mark.asyncio
    async def test_binary_not_found_returns_error_message(self) -> None:
        with patch(
            "maistro.tools.git.github.asyncio.create_subprocess_exec",
            new=AsyncMock(side_effect=FileNotFoundError),
        ):
            code, output = await _run_gh("pr", "list")
        assert code == 1
        assert "not found" in output

    @pytest.mark.asyncio
    async def test_timeout_returns_error_message(self) -> None:
        with (
            patch(
                "maistro.tools.git.github.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=_FakeProc()),
            ),
            patch(
                "maistro.tools.git.github.asyncio.wait_for",
                new=AsyncMock(side_effect=TimeoutError),
            ),
        ):
            code, output = await _run_gh("pr", "list", timeout=5)
        assert code == 1
        assert "timed out after 5s" in output


class TestCreatePr:
    @pytest.mark.asyncio
    async def test_success_extracts_url_from_last_line(self) -> None:
        with patch(
            "maistro.tools.git.github._run_gh",
            new=AsyncMock(return_value=(0, "Creating PR...\nhttps://github.com/org/repo/pull/1\n")),
        ):
            result = await create_pr("org/repo", "feat", "title", "body")
        assert result["success"] is True
        assert result["exit_code"] == 0
        assert result["url"] == "https://github.com/org/repo/pull/1"

    @pytest.mark.asyncio
    async def test_failure_has_no_url(self) -> None:
        with patch(
            "maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(1, "error: failed"))
        ):
            result = await create_pr("org/repo", "feat", "title", "body")
        assert result["success"] is False
        assert result["url"] is None

    @pytest.mark.asyncio
    async def test_success_but_last_line_not_url_has_no_url(self) -> None:
        with patch(
            "maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(0, "not a url"))
        ):
            result = await create_pr("org/repo", "feat", "title", "body")
        assert result["url"] is None

    @pytest.mark.asyncio
    async def test_empty_output_has_no_url(self) -> None:
        with patch("maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(0, ""))):
            result = await create_pr("org/repo", "feat", "title", "body")
        assert result["url"] is None
        assert result["output"] == ""


class TestProjectPr:
    def test_full_shape_projected(self) -> None:
        data = {
            "title": "t",
            "state": "OPEN",
            "body": "x" * (_MAX_PR_BODY + 10),
            "files": [{"path": "a.py", "additions": 1, "deletions": 2}],
            "reviews": [
                {
                    "author": {"login": "bob"},
                    "state": "APPROVED",
                    "body": "y" * (_MAX_REVIEW_BODY + 5),
                }
            ],
        }
        result = _project_pr(data)
        assert result["title"] == "t"
        assert len(result["body"]) == _MAX_PR_BODY
        assert result["changed_file_count"] == 1
        assert result["changed_files"] == [{"path": "a.py", "additions": 1, "deletions": 2}]
        assert result["reviews"][0]["author"] == "bob"
        assert len(result["reviews"][0]["body"]) == _MAX_REVIEW_BODY

    def test_non_list_files_and_reviews_default_empty(self) -> None:
        result = _project_pr({"files": "bad", "reviews": None})
        assert result["changed_files"] == []
        assert result["reviews"] == []

    def test_non_dict_items_in_files_and_reviews_skipped(self) -> None:
        result = _project_pr({"files": ["not-a-dict"], "reviews": ["not-a-dict"]})
        assert result["changed_files"] == []
        assert result["reviews"] == []

    def test_review_author_as_plain_string(self) -> None:
        result = _project_pr({"reviews": [{"author": "alice", "state": "COMMENTED"}]})
        assert result["reviews"][0]["author"] == "alice"

    def test_review_author_missing_defaults_empty_string(self) -> None:
        result = _project_pr({"reviews": [{"state": "COMMENTED"}]})
        assert result["reviews"][0]["author"] == ""

    def test_missing_title_state_body_default(self) -> None:
        result = _project_pr({})
        assert result["title"] == ""
        assert result["state"] == ""
        assert result["body"] == ""


class TestGetPr:
    @pytest.mark.asyncio
    async def test_gh_failure_returns_error(self) -> None:
        with patch(
            "maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(1, "not found"))
        ):
            result = await get_pr("org/repo", 1)
        assert result == {"error": "not found"}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_error(self) -> None:
        with patch("maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(0, "not json"))):
            result = await get_pr("org/repo", 1)
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_non_dict_json_returns_error(self) -> None:
        with patch("maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(0, "[1,2]"))):
            result = await get_pr("org/repo", 1)
        assert "error" in result
        assert "Unexpected gh output shape" in result["error"]

    @pytest.mark.asyncio
    async def test_valid_json_projects_pr(self) -> None:
        with patch(
            "maistro.tools.git.github._run_gh",
            new=AsyncMock(return_value=(0, '{"title": "t", "state": "OPEN"}')),
        ):
            result = await get_pr("org/repo", 1)
        assert result["title"] == "t"
        assert result["state"] == "OPEN"


class TestProjectIssue:
    def test_full_shape_projected(self) -> None:
        data = {
            "number": 5,
            "title": "bug",
            "body": "z" * (_MAX_ISSUE_BODY + 10),
            "labels": [{"name": "bug"}, "manual-label"],
        }
        result = _project_issue(data)
        assert result["number"] == 5
        assert result["title"] == "bug"
        assert len(result["body_excerpt"]) == _MAX_ISSUE_BODY
        assert result["labels"] == ["bug", "manual-label"]

    def test_non_list_labels_default_empty(self) -> None:
        result = _project_issue({"labels": "bad"})
        assert result["labels"] == []

    def test_missing_fields_default(self) -> None:
        result = _project_issue({})
        assert result["number"] is None
        assert result["title"] == ""
        assert result["body_excerpt"] == ""


class TestListIssues:
    @pytest.mark.asyncio
    async def test_gh_failure_returns_empty_list(self) -> None:
        with patch("maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(1, "error"))):
            result = await list_issues("org/repo")
        assert result == []

    @pytest.mark.asyncio
    async def test_invalid_json_returns_empty_list(self) -> None:
        with patch("maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(0, "not json"))):
            result = await list_issues("org/repo")
        assert result == []

    @pytest.mark.asyncio
    async def test_non_list_json_returns_empty_list(self) -> None:
        with patch("maistro.tools.git.github._run_gh", new=AsyncMock(return_value=(0, "{}"))):
            result = await list_issues("org/repo")
        assert result == []

    @pytest.mark.asyncio
    async def test_valid_list_projects_each_dict_item(self) -> None:
        with patch(
            "maistro.tools.git.github._run_gh",
            new=AsyncMock(
                return_value=(0, '[{"number": 1, "title": "a"}, "not-a-dict", {"number": 2}]')
            ),
        ):
            result = await list_issues("org/repo", limit=5)
        assert len(result) == 2
        assert result[0]["number"] == 1
        assert result[1]["number"] == 2
