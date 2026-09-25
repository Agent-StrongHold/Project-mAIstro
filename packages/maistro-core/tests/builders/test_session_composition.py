"""The shipped Builders local-session composition executes on the durable spine.

`maistro.builders.session_composition` is the composition the interactive
Builders TUI runs per user turn (#49/#459): durable SQLite spine ->
canonical ``BuilderPipeline`` -> one ``chat_turn`` stage -> canonical
Run -> NodeRun -> Attempt evidence. The strict-closeout parity suite
(``tests/cross_product_parity``) executes it too, but that suite runs in the
quality gate's ``scripts`` producer — its runs never reach the maistro-core
coverage measurement, so this file pins the composition where it is measured:
a failing wiring regression must be visible to the package's own suite, not
only to a cross-cutting closeout.

Only the model-call boundary is deterministic here (the parity suite's
``DeterministicTurnRunner`` stand-in): everything else — spine wiring,
dispatcher, pipeline construction, canonical execution — is the shipped code
the TUI imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("aiosqlite")


class _DeterministicTurnRunner:
    """Model-call boundary stand-in; raises when asked to (failure leg)."""

    def __init__(self, *, fail: bool = False) -> None:
        self._fail = fail
        self.calls: list[list[dict[str, Any]]] = []

    async def execute_turn(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(messages)
        if self._fail:
            raise RuntimeError("model unavailable")
        user = next(m for m in messages if m["role"] == "user")
        return {"content": f"turn output: {user['content']}"}


@pytest.mark.asyncio
async def test_turn_dispatcher_adapts_one_turn_to_the_stage_seam() -> None:
    """The dispatcher hands the turn prompt to the runner and returns a
    successful DispatchResult — the boundary the canonical stage executes."""
    from maistro.builders.session_composition import TurnDispatcher

    runner = _DeterministicTurnRunner()
    dispatcher = TurnDispatcher(runner)
    assert dispatcher.supports("builder", "chat_turn") is True

    result = await dispatcher.run(
        run_id="run-1",
        node_name="chat_turn",
        agent_name="builder",
        prompt="write a test",
        context={},
    )
    assert result.ok is True
    assert result.output == "turn output: write a test"
    # The system/user pair the shipped agent loop expects.
    roles = [m["role"] for m in runner.calls[0]]
    assert roles == ["system", "user"]


@pytest.mark.asyncio
async def test_open_session_spine_wires_the_durable_execution_spine(
    tmp_path: Path,
) -> None:
    """The factory wires the canonical stores for the session's Workspace and
    resolves its Root Project — no in-memory fallback for a local session."""
    import aiosqlite

    from maistro.builders.session_composition import open_session_spine
    from maistro.graph.durable_runs import CanonicalDurableRunStore

    connection = await aiosqlite.connect(tmp_path / "session.sqlite3")
    try:
        spine = await open_session_spine(connection, workspace_id="builders-session")
        assert spine.workspace_id == "builders-session"
        # The Root Project `wire_execution_spine` creates eagerly.
        assert spine.project_id
        assert isinstance(spine.durable_store, CanonicalDurableRunStore)
        assert spine.run_store is not None
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_build_session_pipeline_executes_a_turn_on_the_canonical_spine(
    tmp_path: Path,
) -> None:
    """One shipped-composition turn leaves canonical Run/NodeRun/Attempt
    evidence and carries the turn output back to the caller."""
    import aiosqlite

    from maistro.builders.session_composition import build_session_pipeline, open_session_spine
    from maistro.runs.wiring import wire_execution_spine

    connection = await aiosqlite.connect(tmp_path / "turn.sqlite3")
    try:
        spine = await open_session_spine(connection, workspace_id="builders-turn")
        pipeline = build_session_pipeline(_DeterministicTurnRunner(), spine=spine)

        product_run = await pipeline.execute(
            issue_number=446,
            title="write a test",
            repo=str(tmp_path),
            skip_decompose=False,
        )

        assert product_run.status == "completed", product_run.failed_stage_error
        assert product_run.context["chat_turn"] == "turn output: write a test"
        assert product_run.canonical_run_id

        # Canonical evidence, read through the stores the pipeline was handed —
        # never a second projection of execution truth.
        _projects, run_store, *_rest = await wire_execution_spine(
            connection, workspace_id="builders-turn"
        )
        run = await run_store.get_run(product_run.canonical_run_id)
        assert run is not None and run.status.value == "completed"
        node_runs = await run_store.list_node_runs(run.run_id)
        assert len(node_runs) == 1
        attempts = await run_store.list_attempts(node_runs[0].node_run_id)
        assert len(attempts) == 1
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_a_failing_turn_fails_the_canonical_run_not_the_session(
    tmp_path: Path,
) -> None:
    """A model-call failure surfaces as a failed canonical Run with the stage
    error named — the composition must not swallow it into a fake success."""
    import aiosqlite

    from maistro.builders.session_composition import build_session_pipeline, open_session_spine
    from maistro.runs.wiring import wire_execution_spine

    connection = await aiosqlite.connect(tmp_path / "failed-turn.sqlite3")
    try:
        spine = await open_session_spine(connection, workspace_id="builders-fail")
        pipeline = build_session_pipeline(_DeterministicTurnRunner(fail=True), spine=spine)

        product_run = await pipeline.execute(
            issue_number=447,
            title="explode",
            repo=str(tmp_path),
            skip_decompose=False,
        )

        assert product_run.status != "completed"
        assert "model unavailable" in product_run.failed_stage_error

        _projects, run_store, *_rest = await wire_execution_spine(
            connection, workspace_id="builders-fail"
        )
        run = await run_store.get_run(product_run.canonical_run_id)
        assert run is not None and run.status.value == "failed"
    finally:
        await connection.close()
