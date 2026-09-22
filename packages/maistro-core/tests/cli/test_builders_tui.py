"""The shipped Builders TUI turn executes on the canonical spine.

`maistro.cli._builders_tui.CodingScreen._run_agent_turn` is the interactive
product surface of the #49 convergence work: each user turn must run through
the shipped session composition (durable SQLite spine -> canonical
``BuilderPipeline`` -> Run -> NodeRun -> Attempt) rather than calling the
agent loop in-process with no evidence. These tests boot the real Textual app
headlessly and drive the turn method itself, replacing only the model-call
boundary (``TurnRunner``) with a deterministic fake — the sandbox, session,
pipeline construction, spine wiring, and canonical execution are the shipped
code.

The canonical evidence is then read back through a second connection to the
turn's SQLite database, because the TUI closes its connection when the turn
ends — durability, not a live handle, is what makes the run observable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("textual")
pytest.importorskip("maistro_bootstrap")


class _FakeTurnRunner:
    """Deterministic stand-in for the bootstrap agent-loop TurnRunner."""

    fail = False

    def __init__(self, *, session: Any, config: Any) -> None:
        self._session = session
        self._config = config
        self._llm: Any = None

    def set_llm(self, llm: Any) -> None:
        self._llm = llm

    async def execute_turn(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self.fail:
            raise RuntimeError("model unavailable")
        user = next(m for m in messages if m["role"] == "user")
        return {"content": f"tui turn: {user['content']}"}


async def _chat_text(screen: Any) -> str:
    from textual.widgets import RichLog

    log = screen.query_one("#chat-log", RichLog)
    return "\n".join(strip.text for strip in log.lines)


async def _canonical_runs(db_path: Path, workspace_id: str) -> dict[str, str]:
    """Read the turn's canonical Run lifecycle from a second connection."""
    import aiosqlite

    from maistro.runs.model import RunStatus
    from maistro.runs.wiring import wire_execution_spine

    connection = await aiosqlite.connect(db_path)
    try:
        _projects, run_store, *_rest = await wire_execution_spine(
            connection, workspace_id=workspace_id
        )
        by_status: dict[str, str] = {}
        for status in (RunStatus.COMPLETED, RunStatus.FAILED):
            for run in await run_store.list_by_status(status, limit=10, workspace_id=None):
                by_status[run.run_id] = status.value
        return by_status
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_a_turn_executes_on_the_canonical_spine_and_reports_the_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.cli._builders_tui import BuildersApp, CodingScreen, WelcomeScreen

    monkeypatch.setenv("HOME", str(tmp_path))  # the TUI writes under ~/.maistro
    monkeypatch.setattr(
        "maistro_bootstrap.builders.agent_loop.TurnRunner", _FakeTurnRunner
    )

    app = BuildersApp()
    async with app.run_test() as pilot:
        await app.query_one(WelcomeScreen).remove()  # the shipped open flow
        screen = CodingScreen("tui-session", "https://example.invalid/repo", tmp_path)
        await app.mount(screen)

        screen._run_agent_turn("write a test")
        await pilot.pause()
        await app.workers.wait_for_complete()

        assert screen._turn_number == 1
        chat = await _chat_text(screen)
        assert "tui turn: write a test" in chat

        runs = await _canonical_runs(
            tmp_path / ".maistro" / "builders" / "runs.sqlite3",
            workspace_id="builders-tui-session",
        )
        assert runs, "the turn left no canonical Run evidence"
        assert all(status == "completed" for status in runs.values()), runs


@pytest.mark.asyncio
async def test_a_failed_turn_is_reported_as_a_failed_canonical_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing model call must surface as a failed Run with the reason in
    the chat — never a fake success and never a silent swallow."""
    from maistro.cli._builders_tui import BuildersApp, CodingScreen, WelcomeScreen

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        "maistro_bootstrap.builders.agent_loop.TurnRunner", _FakeTurnRunner
    )
    _FakeTurnRunner.fail = True
    try:
        app = BuildersApp()
        async with app.run_test() as pilot:
            await app.query_one(WelcomeScreen).remove()  # the shipped open flow
            screen = CodingScreen("tui-fail", "https://example.invalid/repo", tmp_path)
            await app.mount(screen)

            screen._run_agent_turn("explode")
            await pilot.pause()
            await app.workers.wait_for_complete()

            assert screen._turn_number == 1
            chat = await _chat_text(screen)
            assert "Builder run failed" in chat
            assert "model unavailable" in chat

            runs = await _canonical_runs(
                tmp_path / ".maistro" / "builders" / "runs.sqlite3",
                workspace_id="builders-tui-fail",
            )
            assert runs, "the failed turn left no canonical Run evidence"
            assert all(status == "failed" for status in runs.values()), runs
    finally:
        _FakeTurnRunner.fail = False
