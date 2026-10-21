"""Tests for `maistro builders` (maistro.cli._builders)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

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


def test_shipped_tui_admits_turns_through_canonical_adapter() -> None:
    source = (Path(__file__).parents[2] / "src/maistro/cli/_builders_tui.py").read_text()

    assert "BuildersExecutionSpine" in source
    assert "execute_turn(" not in source


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


class TestSessionRunCorrelation:
    """`record_session_run` persists the canonical Run id of an interactive turn.

    Session history stores the exact canonical `run_id`, never the local
    session id dressed up as one: resume and inspection have to name the Run
    the operator can actually inspect (`maistro runs show <run_id>`).
    """

    @staticmethod
    def _sessions(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        import maistro.cli._builders_sessions as sessions

        monkeypatch.setattr(sessions, "_HISTORY_FILE", tmp_path / "builders_sessions.json")
        return sessions

    def test_run_ids_accumulate_deduplicate_and_survive_a_re_record(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sessions = self._sessions(monkeypatch, tmp_path)
        repo = str(tmp_path)

        sessions.record_session("session-1", tmp_path, repo)
        assert sessions.get_session("session-1").canonical_run_ids == []

        sessions.record_session_run("session-1", "run-1")
        # A repeated notification of the same Run must not duplicate the id.
        sessions.record_session_run("session-1", "run-1")
        sessions.record_session_run("session-1", "run-2")

        entry = sessions.get_session("session-1")
        assert entry.canonical_run_ids == ["run-1", "run-2"]

        # Re-opening the repo re-records the session; the correlation is not
        # collateral damage of the resume that displays it.
        sessions.record_session("session-1", tmp_path, repo)
        assert sessions.get_session("session-1").canonical_run_ids == ["run-1", "run-2"]

    def test_an_unknown_session_is_not_created_by_a_run_notification(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sessions = self._sessions(monkeypatch, tmp_path)
        sessions.record_session("session-1", tmp_path, str(tmp_path))
        before = sessions._HISTORY_FILE.read_text(encoding="utf-8")

        sessions.record_session_run("no-such-session", "run-1")

        assert sessions._HISTORY_FILE.read_text(encoding="utf-8") == before
        assert sessions.get_session("no-such-session") is None


class _FakeChat:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def write(self, line: str) -> None:
        self.lines.append(line)


class _FakeBar(_FakeChat):
    def update(self, line: str) -> None:
        self.lines.append(line)


def _install_bootstrap_stubs(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Install the `maistro_bootstrap.builders` modules the TUI imports.

    `maistro-bootstrap` is an optional extra (absent from the base test env),
    so the shipped TUI's execution wiring is driven against recorded stubs —
    the same contract the real modules offer (`BuilderSession`, `TurnRunner`,
    `AgentLoopConfig`, `LocalWorktreeSandbox`, `ResponsesAPICallable`).
    """
    recorded: dict[str, object] = {"sandboxes": [], "runners": [], "sessions": []}

    class _LocalWorktreeSandbox:
        def __init__(self, work_dir: object) -> None:
            recorded["sandboxes"].append(work_dir)  # type: ignore[union-attr]

    class _AgentLoopConfig:
        pass

    class _ResponsesAPICallable:
        pass

    class _BuilderSession:
        def __init__(self, sandbox: object) -> None:
            self.sandbox = sandbox
            self.messages: list[dict[str, str]] = []
            recorded["sessions"].append(self)  # type: ignore[union-attr]

        def add_user(self, text: str) -> None:
            self.messages.append({"role": "user", "content": text})

    class _TurnRunner:
        def __init__(self, session: object, config: object) -> None:
            self.session = session
            self.config = config
            self.llm: object | None = None
            recorded["runners"].append(self)  # type: ignore[union-attr]

        def set_llm(self, llm: object) -> None:
            self.llm = llm

    def _module(name: str, **attrs: object) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        return mod

    monkeypatch.setitem(sys.modules, "maistro_bootstrap", _module("maistro_bootstrap"))
    monkeypatch.setitem(
        sys.modules, "maistro_bootstrap.builders", _module("maistro_bootstrap.builders")
    )
    monkeypatch.setitem(
        sys.modules,
        "maistro_bootstrap.builders.agent_loop",
        _module(
            "maistro_bootstrap.builders.agent_loop",
            AgentLoopConfig=_AgentLoopConfig,
            TurnRunner=_TurnRunner,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "maistro_bootstrap.builders.responses_callable",
        _module(
            "maistro_bootstrap.builders.responses_callable",
            ResponsesAPICallable=_ResponsesAPICallable,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "maistro_bootstrap.builders.sandbox",
        _module("maistro_bootstrap.builders.sandbox", LocalWorktreeSandbox=_LocalWorktreeSandbox),
    )
    monkeypatch.setitem(
        sys.modules,
        "maistro_bootstrap.builders.session",
        _module("maistro_bootstrap.builders.session", BuilderSession=_BuilderSession),
    )
    return recorded


class _RecordingSpine:
    """Stands in for `BuildersExecutionSpine` — records the canonical admission."""

    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []
        self.opens = 0

    async def open(self) -> _RecordingSpine:
        self.opens += 1
        return self

    def executor(self) -> _RecordingSpine:
        return self

    async def execute(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.result


def _drive_coding_screen(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    spine: _RecordingSpine,
    canonical_run_ids: list[str] | None = None,
    recorded_runs: list[tuple[str, str]] | None = None,
):
    """Build a `CodingScreen` under the textual/bootstrap stubs and wire its I/O."""
    import maistro.builders.interactive as interactive

    tui = _import_builders_tui(monkeypatch)
    bootstrap = _install_bootstrap_stubs(monkeypatch)

    async def _open_spine(**kwargs: object) -> _RecordingSpine:
        return await spine.open()

    monkeypatch.setattr(interactive.BuildersExecutionSpine, "open", staticmethod(_open_spine))
    if recorded_runs is not None:
        import maistro.cli._builders_sessions as sessions

        monkeypatch.setattr(
            sessions,
            "record_session_run",
            lambda session_id, run_id: recorded_runs.append((session_id, run_id)),
        )

    screen = tui.CodingScreen(
        "session-1", "https://example.com/repo.git", tmp_path, canonical_run_ids
    )
    chat, bar = _FakeChat(), _FakeBar()
    screen.query_one = lambda selector, *args: (  # type: ignore[method-assign]
        chat if selector == "#chat-log" else bar
    )
    return tui, screen, chat, bar, bootstrap


class TestCodingScreenExecutesOnTheCanonicalSpine:
    """The shipped TUI turn is one canonical Run, not a private execution path."""

    def test_a_turn_is_admitted_with_the_react_runner_as_its_physical_work(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import asyncio

        from maistro.builders.interactive import InteractiveTurnResult
        from maistro.runs.model import RunStatus

        recorded_runs: list[tuple[str, str]] = []
        spine = _RecordingSpine(
            InteractiveTurnResult(
                run_id="run-1", status=RunStatus.COMPLETED, output="edited file", raw_result=None
            )
        )
        _tui, screen, chat, bar, bootstrap = _drive_coding_screen(
            monkeypatch, tmp_path, spine=spine, recorded_runs=recorded_runs
        )

        # Before the first turn the bar names no canonical run.
        assert "canonical run:[/bold] none" in screen._session_bar_text()

        asyncio.run(screen._run_agent_turn("edit the file"))
        asyncio.run(screen._run_agent_turn("and again"))

        assert [call["session_id"] for call in spine.calls] == ["session-1", "session-1"]
        assert [call["repo"] for call in spine.calls] == [str(tmp_path), str(tmp_path)]
        assert [call["prompt"] for call in spine.calls] == ["edit the file", "and again"]
        # The system prompt plus the session's own ReAct history is what the
        # canonical attempt executes — the TUI does not build a second one.
        assert spine.calls[0]["messages"] == [
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": "edit the file"},
        ]
        # The runner handed to the canonical executor is the cached TurnRunner
        # (a second `_get_execution` must not build another execution path).
        assert spine.calls[0]["runner"] is spine.calls[1]["runner"]
        assert spine.calls[0]["runner"] is screen._turn_runner
        assert len(bootstrap["runners"]) == 1
        assert len(bootstrap["sandboxes"]) == 1
        assert spine.opens == 1

        assert screen.canonical_run_ids == ["run-1", "run-1"]
        assert recorded_runs == [("session-1", "run-1"), ("session-1", "run-1")]
        assert "canonical run:[/bold] run-1" in bar.lines[-1]
        assert "\n[bold green]agent:[/bold green] edited file" in chat.lines

    def test_a_failed_canonical_run_is_reported_with_its_run_id(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import asyncio

        from maistro.builders.interactive import InteractiveTurnResult
        from maistro.runs.model import RunStatus

        spine = _RecordingSpine(
            InteractiveTurnResult(
                run_id="run-bad",
                status=RunStatus.FAILED,
                output="ignored",
                raw_result=None,
                error="interactive turn stopped: max_turns",
            )
        )
        _tui, screen, chat, _bar, _bootstrap = _drive_coding_screen(
            monkeypatch, tmp_path, spine=spine, recorded_runs=[]
        )

        asyncio.run(screen._run_agent_turn("keep going"))

        assert chat.lines == [
            "[red]Canonical run run-bad failed: interactive turn stopped: max_turns[/red]"
        ]
        # The canonical identity is still recorded: a failed Run is evidence the
        # operator can inspect, not a turn that never happened.
        assert screen.canonical_run_ids == ["run-bad"]


class TestResumeCarriesTheCanonicalRunIdentity:
    """Resume restores the exact Run ids the session produced."""

    def test_open_coding_screen_mounts_the_session_with_its_run_ids(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        tui = _import_builders_tui(monkeypatch)
        created: list[tuple[tuple[object, ...], dict[str, object]]] = []
        removed: list[bool] = []

        class _Recorder:
            def __init__(self, *args: object, **kwargs: object) -> None:
                created.append((args, kwargs))

        class _Welcome:
            def remove(self) -> None:
                removed.append(True)

        monkeypatch.setattr(tui, "CodingScreen", _Recorder)
        app = object.__new__(tui.BuildersApp)
        app.query_one = lambda *args, **kwargs: _Welcome()  # type: ignore[method-assign]
        mounted: list[object] = []
        app.mount = lambda widget: mounted.append(widget)  # type: ignore[method-assign]

        app._open_coding_screen(
            "session-1", "https://example.com/repo.git", tmp_path, canonical_run_ids=["run-1"]
        )

        assert removed == [True]
        assert created == [(("session-1", "https://example.com/repo.git", tmp_path, ["run-1"]), {})]
        # The screen is mounted exactly once, with the resumed identity.
        assert len(mounted) == 1

    def test_resuming_a_recorded_session_passes_its_canonical_run_ids(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from maistro.cli._builders_sessions import BuilderSessionEntry

        tui = _import_builders_tui(monkeypatch)
        entry = BuilderSessionEntry(
            id="session-1",
            path=str(tmp_path),
            repo_url="https://example.com/repo.git",
            canonical_run_ids=["run-1", "run-2"],
        )
        monkeypatch.setattr(tui, "get_session", lambda session_id: entry)
        app = object.__new__(tui.BuildersApp)
        app.query_one = lambda *args, **kwargs: _FakeBar()  # type: ignore[method-assign]
        opened: list[tuple[tuple[object, ...], dict[str, object]]] = []
        app._open_coding_screen = lambda *args, **kwargs: opened.append((args, kwargs))  # type: ignore[method-assign]

        app._on_session_picked("session-1")

        assert opened == [
            (
                ("session-1", "https://example.com/repo.git", tmp_path),
                {"canonical_run_ids": ["run-1", "run-2"]},
            )
        ]
