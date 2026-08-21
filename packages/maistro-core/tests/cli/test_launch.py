"""Tests for `maistro launch` (maistro.cli._launch)."""

from __future__ import annotations

import os
import sys

import pytest

from maistro.cli._launch import launch_server, launch_tui


class TestLaunchServer:
    def test_builds_uvicorn_command_without_reload(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(os, "execvp", lambda prog, args: calls.append(list(args)))

        launch_server(host="127.0.0.1", port=9000, reload=False)

        assert calls == [
            [
                sys.executable,
                "-m",
                "uvicorn",
                "maistro_server.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "9000",
            ]
        ]
        assert "Starting maistro server on 127.0.0.1:9000" in capsys.readouterr().out

    def test_builds_uvicorn_command_with_reload_flag_appended(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []
        monkeypatch.setattr(os, "execvp", lambda prog, args: calls.append(list(args)))

        launch_server(host="0.0.0.0", port=8000, reload=True)

        assert calls[0][-1] == "--reload"


class TestLaunchTui:
    def test_prints_placeholder_and_hint(self, capsys: pytest.CaptureFixture[str]) -> None:
        launch_tui()

        out = capsys.readouterr().out
        assert "coming soon" in out
        assert "maistro builders" in out
