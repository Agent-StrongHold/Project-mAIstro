"""Tests for `maistro builders` (maistro.cli._builders)."""

from __future__ import annotations

import sys
import types

import pytest
import typer

from maistro.cli._builders import _launch_app, builders_main


class TestLaunchApp:
    def test_missing_textual_prints_install_hint_and_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(
            sys.modules,
            "maistro.cli._builders_tui",
            None,  # forces ImportError on `from maistro.cli._builders_tui import BuildersApp`
        )
        with pytest.raises(typer.Exit):
            _launch_app()

    def test_app_runs_when_textual_is_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ran: list[bool] = []

        class _FakeBuildersApp:
            def run(self) -> None:
                ran.append(True)

        fake_module = types.ModuleType("maistro.cli._builders_tui")
        fake_module.BuildersApp = _FakeBuildersApp  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "maistro.cli._builders_tui", fake_module)

        _launch_app()

        assert ran == [True]


class TestBuildersMain:
    def test_callback_delegates_to_launch_app(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called: list[bool] = []
        monkeypatch.setattr("maistro.cli._builders._launch_app", lambda: called.append(True))

        builders_main()

        assert called == [True]
