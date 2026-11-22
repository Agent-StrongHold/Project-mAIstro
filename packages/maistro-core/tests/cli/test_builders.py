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
            "https://example.com/some.path.git",  # suffix rule intact for schemed forms
        ],
    )
    def test_url_forms_still_classify_as_urls(
        self, monkeypatch: pytest.MonkeyPatch, url: str
    ) -> None:
        # Classification says "treat this as a URL", not "this may be
        # cloned": acceptance is `validate_clone_source`'s verdict in
        # `_open_repo`, asserted at runtime below. `http://` deliberately
        # classifies as a URL — and is deliberately refused by the policy
        # gate, because unauthenticated transport is exactly what #404
        # removes.
        _is_git_url = _import_is_git_url(monkeypatch)

        assert _is_git_url(url) is True

    def test_local_paths_are_still_not_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _is_git_url = _import_is_git_url(monkeypatch)

        assert _is_git_url("/home/dev/some/repo") is False
        assert _is_git_url("./relative/repo") is False


def _import_builders_tui(monkeypatch: pytest.MonkeyPatch):
    """Import the whole `_builders_tui` module under the minimal textual stub
    (same stub contract as `_import_is_git_url`) so the runtime path — not
    just the classification helper — can be driven."""
    import types

    def _module(name: str, **attrs: object) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        return mod

    class _Widget:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    def _generic(name: str) -> type:
        return type(name, (), {"__class_getitem__": classmethod(lambda cls, item: cls)})

    widget_names = ("Button", "Footer", "Header", "Input", "Label", "RichLog", "Static")

    def _eventful_widget(name: str) -> type:
        return type(
            name,
            (_Widget,),
            {"Submitted": type("Submitted", (), {}), "Pressed": type("Pressed", (), {})},
        )

    stubs = {
        "textual": _module(
            "textual",
            on=lambda *a: lambda f: f,
            work=lambda f=None, *a, **k: f if f is not None else (lambda g: g),
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

    import maistro.cli._builders_tui as tui

    return tui


class _FakeRecent:
    """Records what the app would render into the `#recent-sessions` label."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def update(self, message: str) -> None:
        self.messages.append(message)


class TestTheCloneGateStopsTheSubprocess:
    """`_open_repo` is where classification becomes a `git clone` subprocess
    (#404). A source the policy refuses must be named and blocked at runtime —
    before any subprocess, session record, or screen change: the git://
    verdict whatever casing the operator typed, and the shared
    `validate_clone_source` verdict for everything else (unauthenticated
    http://, off-allowlist hosts, scp-style spellings, `-`-prefixed flag
    strings that the `.git` suffix rule would otherwise march into argv)."""

    @staticmethod
    def _drive(monkeypatch: pytest.MonkeyPatch, repo: str) -> list[str]:
        import asyncio
        import subprocess

        tui = _import_builders_tui(monkeypatch)
        monkeypatch.delenv("MAISTRO_GIT_CLONE_ALLOWED_HOSTS", raising=False)
        label = _FakeRecent()
        app = object.__new__(tui.BuildersApp)
        app.query_one = lambda *args: label  # type: ignore[method-assign]

        def no_subprocess(*args: object, **kwargs: object) -> object:
            raise AssertionError(f"{repo!r} must never reach the clone subprocess")

        monkeypatch.setattr(subprocess, "run", no_subprocess)

        def no_record(*args: object, **kwargs: object) -> object:
            raise AssertionError(f"{repo!r} must never be recorded as a session")

        monkeypatch.setattr(tui, "record_session", no_record)

        asyncio.run(app._open_repo(repo))  # @work is the identity under the stub
        return label.messages

    @pytest.mark.parametrize(
        "repo",
        [
            "git://github.com/org/repo.git",
            "GIT://github.com/org/repo",
            "http://example.com/repo.git",
            "HTTP://example.com/repo.git",
            "https://evil.example/repo.git",
            "git@github.com:example/repo.git",
            "--upload-pack=evil.git",
        ],
    )
    def test_policy_refused_sources_are_named_and_blocked_at_runtime(
        self, monkeypatch: pytest.MonkeyPatch, repo: str
    ) -> None:
        messages = self._drive(monkeypatch, repo)

        assert len(messages) == 1
        assert "Blocked" in messages[0]

    def test_a_local_path_still_takes_the_directory_branch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """The gate is on the transport, not on opening repos: a path that is
        not a URL proceeds to the directory check (and gets the honest 'not a
        directory' verdict when it does not exist) — no subprocess, no
        policy message."""
        messages = self._drive(monkeypatch, str(tmp_path / "missing"))

        assert len(messages) == 1
        assert "Not a directory" in messages[0]


class TestTheAllowedTransportClonesUnderTheSamePolicy:
    """A URL the policy admits still reaches git — but through the same
    executable enforcement as the MCP tool: the `-c` protocol/redirect pins
    ride in the argv and the URL sits after `--`, where no scheme can be
    re-read as flags."""

    def test_allowed_https_source_uses_the_digest_pinning_clone_authority(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import asyncio
        from unittest.mock import AsyncMock

        tui = _import_builders_tui(monkeypatch)
        monkeypatch.delenv("MAISTRO_GIT_CLONE_ALLOWED_HOSTS", raising=False)
        label = _FakeRecent()
        app = object.__new__(tui.BuildersApp)
        app.query_one = lambda *args: label  # type: ignore[method-assign]
        clone = AsyncMock(return_value={"success": True, "pinned_commit": "a" * 40})
        monkeypatch.setattr(tui, "git_clone", clone)

        def no_record(*args: object, **kwargs: object) -> None:
            raise AssertionError("test ends after the shared clone authority")

        monkeypatch.setattr(tui, "record_session", no_record)

        asyncio.run(app._open_repo("https://github.com/example/repo.git"))

        assert label.messages and "Blocked" not in label.messages[0]
        clone.assert_awaited_once()
        url, dest = clone.await_args.args[:2]
        assert url == "https://github.com/example/repo.git"
        assert clone.await_args.kwargs == {"timeout": 120}
        assert dest.startswith(str(tui._BUILDERS_CACHE_DIR))
