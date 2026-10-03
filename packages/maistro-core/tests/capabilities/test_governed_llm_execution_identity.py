"""The compatibility adapter consumes canonical IDs and never invents admission."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.capabilities.model_chat import GovernedLLMClient, ModelCallResult, ModelChatEgress
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.observability.correlation import bind_execution_context, detached_execution_context
from maistro.runs.store import RunIntegrityError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[GovernedLLMClient, list[dict[str, Any]]]:
    calls: list[dict[str, Any]] = []

    async def record(self: ModelChatEgress, **kwargs: Any) -> ModelCallResult:
        calls.append(kwargs)
        return ModelCallResult(invocation_id="invocation", model="model", body={"ok": True})

    monkeypatch.setattr(ModelChatEgress, "complete", record)
    # Only the adapter boundary is exercised; egress dependencies are never used.
    return GovernedLLMClient(
        None,  # type: ignore[arg-type]
        registry=None,  # type: ignore[arg-type]
        router=None,  # type: ignore[arg-type]
        endpoint=GatewayEndpoint(base_url="http://unused"),
        workspace_id="workspace",
    ), calls


def ids(suffix: str = "A") -> dict[str, str]:
    return {
        "run_id": f"run-{suffix}",
        "node_run_id": f"node-{suffix}",
        "attempt_id": f"attempt-{suffix}",
    }


@pytest.mark.parametrize("explicit", [None, "", "run-A"])
async def test_exact_bound_identity_and_counter(client: Any, explicit: str | None) -> None:
    adapter, calls = client
    with detached_execution_context(), bind_execution_context(**ids()):
        adapter.set_turn(explicit, agent_name="must-not-manufacture-node")
        assert await adapter.complete([], "model") == {"ok": True}
        await adapter.complete([], "model")
        adapter.clear_turn()
        assert adapter._turn.get() is None
        assert adapter._sequence.get() == 0
        adapter.set_turn()
        await adapter.complete([], "model")
    assert [{key: call[key] for key in ids()} for call in calls] == [ids()] * 3
    assert [call["effect_key"] for call in calls] == ["agent-llm-1", "agent-llm-2", "agent-llm-1"]


@pytest.mark.parametrize("missing", ["run_id", "node_run_id", "attempt_id", "all"])
@pytest.mark.parametrize("value", ["", " \t\n"])
async def test_missing_identity_refuses_before_sequence_or_egress(
    client: Any, missing: str, value: str
) -> None:
    adapter, calls = client
    context = {
        key: value if key == missing or missing == "all" else val for key, val in ids().items()
    }
    with detached_execution_context(), bind_execution_context(**context):
        with pytest.raises(RunIntegrityError):
            adapter.set_turn()
        with pytest.raises(RunIntegrityError):
            await adapter.complete([], "model")
    assert adapter._turn.get() is None
    assert adapter._sequence.get() == 0
    assert calls == []


@pytest.mark.parametrize("explicit", ["other-run", " \t"])
async def test_conflicting_explicit_run_refuses(client: Any, explicit: str) -> None:
    adapter, calls = client
    with (
        detached_execution_context(),
        bind_execution_context(**ids()),
        pytest.raises(RunIntegrityError),
    ):
        adapter.set_turn(explicit)
    assert adapter._turn.get() is None
    assert adapter._sequence.get() == 0
    assert calls == []


async def test_complete_reads_context_without_prior_set_turn(client: Any) -> None:
    adapter, calls = client
    with detached_execution_context(), bind_execution_context(**ids()):
        await adapter.complete([], "model")
    assert {key: calls[0][key] for key in ids()} == ids()
    assert calls[0]["effect_key"] == "agent-llm-1"


@pytest.mark.parametrize("clear", [False, True])
async def test_ended_context_cannot_reuse_turn(client: Any, clear: bool) -> None:
    adapter, calls = client
    with detached_execution_context():
        with bind_execution_context(**ids()):
            adapter.set_turn()
            await adapter.complete([], "model")
            if clear:
                adapter.clear_turn()
        sequence = adapter._sequence.get()
        with pytest.raises(RunIntegrityError):
            await adapter.complete([], "model")
        assert adapter._sequence.get() == sequence
    assert len(calls) == 1


@pytest.mark.parametrize("changed", ["run_id", "node_run_id", "attempt_id"])
async def test_changed_context_requires_explicit_new_turn(client: Any, changed: str) -> None:
    adapter, calls = client
    with detached_execution_context(), bind_execution_context(**ids()):
        adapter.set_turn()
        await adapter.complete([], "model")
        with bind_execution_context(**{changed: "changed"}):
            with pytest.raises(RunIntegrityError):
                await adapter.complete([], "model")
            assert adapter._sequence.get() == 1
            assert len(calls) == 1
            adapter.set_turn()
            await adapter.complete([], "model")
    assert calls[-1][changed] == "changed"
    assert calls[-1]["effect_key"] == "agent-llm-1"


@pytest.mark.parametrize("invalid", ["missing", "mismatched"])
async def test_failed_set_turn_clears_prior_valid_state(client: Any, invalid: str) -> None:
    adapter, calls = client
    with detached_execution_context():
        with bind_execution_context(**ids()):
            adapter.set_turn()
            # Exercise clearing a nonzero prior sequence without issuing egress.
            adapter._sequence.set(7)
            if invalid == "mismatched":
                with pytest.raises(RunIntegrityError):
                    adapter.set_turn("other-run")
        if invalid == "missing":
            with pytest.raises(RunIntegrityError):
                adapter.set_turn()
        assert adapter._turn.get() is None
        assert adapter._sequence.get() == 0
        with pytest.raises(RunIntegrityError):
            await adapter.complete([], "model")
    assert calls == []


async def test_shared_client_keeps_task_local_identity_and_sequence(client: Any) -> None:
    adapter, calls = client
    barrier = asyncio.Barrier(2)

    async def complete_turn(suffix: str) -> None:
        with detached_execution_context(), bind_execution_context(**ids(suffix)):
            adapter.set_turn()
            await barrier.wait()
            await adapter.complete([], "model")
            await barrier.wait()
            await adapter.complete([], "model")
            adapter.clear_turn()

    await asyncio.gather(complete_turn("A"), complete_turn("B"))
    for suffix in ("A", "B"):
        own = [call for call in calls if call["run_id"] == f"run-{suffix}"]
        assert [{key: call[key] for key in ids()} for call in own] == [ids(suffix)] * 2
        assert [call["effect_key"] for call in own] == ["agent-llm-1", "agent-llm-2"]
    assert adapter._turn.get() is None
    assert adapter._sequence.get() == 0
