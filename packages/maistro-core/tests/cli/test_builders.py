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


def _import_is_git_url(monkeypatch: pytest.MonkeyPatch):
    """Import `_builders_tui._is_git_url` with a minimal textual stub.

    textual is an optional TUI dependency that the test environment does not
    install, but the module binds a fixed, small set of names from it at
    import time. Stubbing just those names lets the pure classification
    helper — the gate on the TUI's clone subprocess — be exercised directly.
    """

    def _module(name: str, **attrs: object) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        return mod

    class _Widget:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    def _generic(name: str) -> type:
        # Class-level subscription (`ModalScreen[str | None]`) must resolve.
        return type(name, (), {"__class_getitem__": classmethod(lambda cls, item: cls)})

    widget_names = ("Button", "Footer", "Header", "Input", "Label", "RichLog", "Static")

    def _eventful_widget(name: str) -> type:
        # `@on(Input.Submitted, ...)` / `Button.Pressed` read event types off
        # the widget class at import time.
        return type(
            name,
            (_Widget,),
            {"Submitted": type("Submitted", (), {}), "Pressed": type("Pressed", (), {})},
        )

    stubs = {
        "textual": _module(
            "textual",
            on=lambda *a: lambda f: f,  # @on(...) -> decorator
            work=lambda f=None, *a, **k: f if f is not None else (lambda g: g),  # @work and @work()
        ),
        "textual.app": _module("textual.app", App=_generic("App"), ComposeResult=object),
        "textual.binding": _module("textual.binding", Binding=lambda *a, **k: None),
        "textual.containers": _module(
            "textual.containers",
            Horizontal=type("Horizontal", (_Widget,), {}),
            Vertical=type("Vertical", (_Widget,), {}),
        ),
        "textual.screen": _module("textual.screen", ModalScreen=_generic("ModalScreen")),
        "textual.widgets": _module(
            "textual.widgets",
            **{name: _eventful_widget(name) for name in widget_names},
        ),
    }
    for name, mod in stubs.items():
        monkeypatch.setitem(sys.modules, name, mod)

    from maistro.cli._builders_tui import _is_git_url

    return _is_git_url


class TestGitUrlClassification:
    """`_is_git_url` gates the builders TUI's `git clone` subprocess (#404).

    The `.endswith('.git')` catch-all used to wave `git://host/repo.git` —
    the unauthenticated, unencrypted protocol — straight into a clone; the
    rejection must be explicit and casing-proof (git parses remote schemes
    case-insensitively, RFC 3986).
    """

    @pytest.mark.parametrize(
        "url",
        [
            "git://example.com/repo.git",
            "git://example.com/repo",
            "GIT://example.com/repo.GIT",
            "Git://example.com/repo.git",
        ],
    )
    def test_git_protocol_is_never_classified_as_a_clonable_url(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        _is_git_url = _import_is_git_url(monkeypatch)

        assert _is_git_url(url) is False

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/repo.git",
            "https://example.com/repo",
            "ssh://git@example.com/repo",
            "git@github.com:example/repo.git",
            "http://example.com/repo.git",
            "https://example.com/some.path.git",  # suffix rule intact for authenticated forms
        ],
    )
    def test_authenticated_transports_still_classify_as_urls(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        _is_git_url = _import_is_git_url(monkeypatch)

        assert _is_git_url(url) is True

    def test_local_paths_are_still_not_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _is_git_url = _import_is_git_url(monkeypatch)

        assert _is_git_url("/home/dev/some/repo") is False
        assert _is_git_url("./relative/repo") is False
