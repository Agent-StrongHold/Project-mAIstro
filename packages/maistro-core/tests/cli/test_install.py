"""Tests for maistro.cli._install — `maistro install` subcommand."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from maistro.cli._install import install_main


class TestInstallMain:
    def test_delegates_to_bootstrap_when_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        run_mock = MagicMock()
        cli_module = ModuleType("maistro_bootstrap.cli")
        cli_module.run = run_mock  # type: ignore[attr-defined]
        bootstrap_module = ModuleType("maistro_bootstrap")
        monkeypatch.setitem(sys.modules, "maistro_bootstrap", bootstrap_module)
        monkeypatch.setitem(sys.modules, "maistro_bootstrap.cli", cli_module)

        install_main()

        run_mock.assert_called_once_with()

    def test_exits_with_error_when_not_installed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "maistro_bootstrap", None)
        monkeypatch.setitem(sys.modules, "maistro_bootstrap.cli", None)

        with pytest.raises(SystemExit) as exc_info:
            install_main()

        assert exc_info.value.code == 1
