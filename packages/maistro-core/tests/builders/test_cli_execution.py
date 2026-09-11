"""Reachable interactive Builders composition uses canonical execution."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from maistro.builders.cli_execution import CanonicalBuilderTurnExecutor
from maistro.runs.model import RunStatus


class _FakeRunner:
    def __init__(self, *, session: object, config: object) -> None:
        self.session = session
        self.config = config
        self.llm = None

    def set_llm(self, llm: object) -> None:
        self.llm = llm

    async def execute_turn(self, *, messages: list[dict[str, object]]) -> dict[str, object]:
        return {"content": f"handled: {messages[-1]['content']}", "stop_reason": "end"}


@pytest.mark.asyncio
async def test_interactive_turn_runner_is_inside_canonical_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro_bootstrap.builders import agent_loop

    monkeypatch.setattr(agent_loop, "TurnRunner", _FakeRunner)
    executor = CanonicalBuilderTurnExecutor(workspace_id="builders-cli-test")

    result = await executor.execute_turn(
        session=SimpleNamespace(workspace_path="/tmp/repo"),
        config=SimpleNamespace(),
        messages=[{"role": "user", "content": "inspect this"}],
        llm=lambda *args, **kwargs: {},
    )

    assert result["content"] == "handled: inspect this"
    assert result["canonical_run_id"]
    assert result["canonical_graph_id"]
    assert executor.last_record is not None
    assert executor.last_record.run.status is RunStatus.COMPLETED
    assert len(executor.last_record.node_runs) == 1
    assert len(executor.last_record.attempts) == 1
