"""Tests for the shadow git workspace (SPEC-254 / ADR-049)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from maistro.tools.git.shadow import create_shadow_workspace


def _log_count(workspace_ref: Path) -> int:
    result = subprocess.run(
        ["git", "log", "--oneline"], cwd=workspace_ref, capture_output=True, text=True, check=True
    )
    return len(result.stdout.strip().splitlines())


class TestCreateWorkspace:
    def test_creates_repo_with_base_commit(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        assert ws.workspace_ref.is_dir()
        assert ws.base_sha
        assert _log_count(ws.workspace_ref) == 1

    def test_diff_against_base_empty_before_edits(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        assert ws.diff_against_base() == ""

    @pytest.mark.parametrize("task_id", ["../escape", "/tmp/escape", "bad/id", "", "x" * 101])
    def test_rejects_task_ids_that_escape_shadow_root(self, tmp_path: Path, task_id: str) -> None:
        with pytest.raises(ValueError):
            create_shadow_workspace(tmp_path, task_id)


class TestCommitEdit:
    def test_two_edits_produce_two_commits(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        ws.commit_edit({"b.txt": "world"}, "add b.txt")
        assert _log_count(ws.workspace_ref) == 3  # base + 2 edits

    def test_commit_edit_returns_sha(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        sha = ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        assert len(sha) >= 7

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.commit_edit({"nested/dir/file.txt": "content"}, "nested file")
        assert (ws.workspace_ref / "nested" / "dir" / "file.txt").read_text() == "content"

    def test_diff_against_base_reflects_edits(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        assert "a.txt" in ws.diff_against_base()

    @pytest.mark.parametrize("rel_path", ["../escape.txt", "../../escape.txt", "/tmp/escape.txt"])
    def test_commit_edit_rejects_paths_outside_shadow_workspace(
        self, tmp_path: Path, rel_path: str
    ) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        outside = tmp_path / "escape.txt"
        with pytest.raises(ValueError):
            ws.commit_edit({rel_path: "owned"}, "attempt escape")
        assert not outside.exists()


class TestProducePrCandidate:
    def test_squashes_multiple_commits_into_one_diff(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        ws.commit_edit({"b.txt": "world"}, "add b.txt")
        candidate = ws.produce_pr_candidate(base=ws.base_sha, branch="pr-1")
        assert "a.txt" in candidate.squashed_diff
        assert "b.txt" in candidate.squashed_diff

    def test_files_changed_lists_all_touched_files_no_duplicates(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        ws.commit_edit({"a.txt": "hello again", "b.txt": "world"}, "edit a, add b")
        candidate = ws.produce_pr_candidate(base=ws.base_sha, branch="pr-1")
        assert sorted(candidate.files_changed) == ["a.txt", "b.txt"]


class TestDiscard:
    def test_discard_removes_workspace(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        ws.discard()
        assert not ws.workspace_ref.exists()

    def test_discard_does_not_touch_real_tree(self, tmp_path: Path) -> None:
        real_tree = tmp_path / "real"
        real_tree.mkdir()
        (real_tree / "important.txt").write_text("do not touch")

        shadow_root = tmp_path / "shadows"
        ws = create_shadow_workspace(shadow_root, "task-1")
        ws.commit_edit({"a.txt": "hello"}, "add a.txt")
        ws.discard()

        assert (real_tree / "important.txt").read_text() == "do not touch"

    def test_discard_idempotent(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path, "task-1")
        ws.discard()
        ws.discard()

        assert not ws.workspace_ref.exists()

    def test_discard_refuses_workspace_outside_shadow_root(self, tmp_path: Path) -> None:
        ws = create_shadow_workspace(tmp_path / "shadow-root", "task-1")
        outside = tmp_path / "outside"
        outside.mkdir()
        ws.workspace_ref = outside
        with pytest.raises(ValueError, match="outside shadow root"):
            ws.discard()
        assert outside.exists()
