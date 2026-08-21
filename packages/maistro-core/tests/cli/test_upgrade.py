"""Tests for `maistro upgrade` (maistro.cli._upgrade).

Uses monkeypatch on subprocess.run (the external boundary) rather than
mocking the function under test.
"""

from __future__ import annotations

import subprocess

import pytest

from maistro.cli._upgrade import upgrade_main


class _Completed:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestUpgradeMain:
    def test_successful_pull_and_sync(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: object) -> _Completed:
            calls.append(args)
            if args[0] == "git":
                return _Completed(0, stdout="Already up to date.\n")
            return _Completed(0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        upgrade_main()

        out = capsys.readouterr().out
        assert "Already up to date." in out
        assert "Dependencies synced." in out
        assert calls[0][:2] == ["git", "pull"]
        assert calls[1] == ["uv", "sync", "--all-extras"]

    def test_git_pull_nonzero_returncode_prints_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_run(args: list[str], **kwargs: object) -> _Completed:
            if args[0] == "git":
                return _Completed(1, stderr="conflict during rebase\n")
            return _Completed(0)

        monkeypatch.setattr(subprocess, "run", fake_run)

        upgrade_main()

        out = capsys.readouterr().out
        assert "conflict during rebase" in out
        assert "Dependencies synced." in out

    def test_git_not_found_returns_early(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_run(args: list[str], **kwargs: object) -> _Completed:
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        upgrade_main()

        out = capsys.readouterr().out
        assert "git not found" in out
        assert "Syncing dependencies" not in out

    def test_git_pull_timeout_returns_early(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_run(args: list[str], **kwargs: object) -> _Completed:
            raise subprocess.TimeoutExpired(cmd=args, timeout=60)

        monkeypatch.setattr(subprocess, "run", fake_run)

        upgrade_main()

        out = capsys.readouterr().out
        assert "git pull timed out" in out
        assert "Syncing dependencies" not in out

    def test_uv_sync_file_not_found_prints_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_run(args: list[str], **kwargs: object) -> _Completed:
            if args[0] == "git":
                return _Completed(0, stdout="ok\n")
            raise FileNotFoundError("uv not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        upgrade_main()

        out = capsys.readouterr().out
        assert "Dependency sync failed" in out

    def test_uv_sync_called_process_error_prints_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def fake_run(args: list[str], **kwargs: object) -> _Completed:
            if args[0] == "git":
                return _Completed(0, stdout="ok\n")
            raise subprocess.CalledProcessError(1, args)

        monkeypatch.setattr(subprocess, "run", fake_run)

        upgrade_main()

        out = capsys.readouterr().out
        assert "Dependency sync failed" in out
