"""The governed model client carries canonical execution identity (#1827).

`GovernedLLMClient` sits between Agent strategies and `ModelChatEgress`. Its
`set_turn` seam must consume the Run/NodeRun/Attempt triple that canonical
execution already bound on the correlation context — `RunExecutionService`
binds `run_id`, `AttemptExecutionService.execute_claimed` binds
`node_run_id`/`attempt_id` — and must never fabricate an
agent-turn/agent-node/agent-attempt id to make an unadmitted call look
governed. These tests pin that adapter boundary with a recording admitted-call
double: exact identity forwarding, refusal on missing/blank/mismatched ids,
failure-atomic `set_turn`, stale-turn refusal in `complete`, per-task identity
isolation, and the per-turn effect-key counter.

The ids provide correlation, not authorization; Binding/credential/policy
checks stay at the governed effect boundary these tests stub out.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, create_autospec

import pytest

from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.model_chat import (
    GovernedLLMClient,
    ModelCallResult,
)
from maistro.observability.correlation import (
    bind_execution_context,
    current_execution_context,
    detached_execution_context,
)
from maistro.runs.store import RunIntegrityError

pytestmark = pytest.mark.contract("behavioral")

RUN_A, NODE_A, ATTEMPT_A = "run-A", "node-A", "attempt-A"
RUN_B, NODE_B, ATTEMPT_B = "run-B", "node-B", "attempt-B"


def _egress_result() -> ModelCallResult:
    return ModelCallResult(
        invocation_id="inv-recorded",
        model="fast-model",
        body={"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
    )


@pytest.fixture
def governed_client() -> tuple[
    GovernedLLMClient,
    AsyncMock,
]:
    """One governed client whose AdmittedModelCalls is a recording test double.

    Only the adapter boundary is exercised: Binding, credential and policy
    machinery live behind the stubbed `AdmittedModelCalls.complete`, so every
    assertion below is about the identity the client forwards to it.
    """
    calls = create_autospec(AdmittedModelCalls, instance=True)
    recorded = AsyncMock(return_value=_egress_result())
    calls.complete = recorded
    client = GovernedLLMClient(calls)
    return client, recorded


def _forwarded(recorded: AsyncMock, call: int = 0) -> tuple[str, str, str]:
    kwargs = recorded.call_args_list[call].kwargs
    return kwargs["identity"]


async def _complete(client: GovernedLLMClient) -> dict[str, Any]:
    return await client.complete([{"role": "user", "content": "hello"}], "fast-model")


# --- exact identity forwarding -------------------------------------------------


async def test_matching_explicit_run_id_forwards_exact_bound_tuple(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A)
        await _complete(client)

    recorded.assert_awaited_once()
    assert _forwarded(recorded) == (RUN_A, NODE_A, ATTEMPT_A)


async def test_omitted_run_id_reads_the_same_bound_tuple(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn()
        await _complete(client)

    recorded.assert_awaited_once()
    assert _forwarded(recorded) == (RUN_A, NODE_A, ATTEMPT_A)


async def test_agent_name_cannot_manufacture_a_node_id(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """`agent_name` qualifies effects only: the bound node id always wins."""
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A, agent_name="writer")
        await _complete(client)

    recorded.assert_awaited_once()
    assert _forwarded(recorded) == (RUN_A, NODE_A, ATTEMPT_A)


async def test_complete_without_prior_set_turn_reads_complete_bound_context(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        await _complete(client)

    recorded.assert_awaited_once()
    assert _forwarded(recorded) == (RUN_A, NODE_A, ATTEMPT_A)


# --- refusal on missing / blank / conflicting identity -------------------------


@pytest.mark.parametrize(
    ("missing", "bind"),
    [
        ("run_id", {"node_run_id": NODE_A, "attempt_id": ATTEMPT_A}),
        ("node_run_id", {"run_id": RUN_A, "attempt_id": ATTEMPT_A}),
        ("attempt_id", {"run_id": RUN_A, "node_run_id": NODE_A}),
        ("all", {}),
        ("node_run_id", {"run_id": RUN_A, "node_run_id": " \t ", "attempt_id": ATTEMPT_A}),
    ],
)
async def test_incomplete_context_refuses_with_zero_egress(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
    missing: str,
    bind: dict[str, str],
) -> None:
    """Missing-id fixtures run detached: blank binds do not erase inherited
    ids, so the only way to hold *no* run id is to hold no context at all."""
    client, recorded = governed_client
    with detached_execution_context(), bind_execution_context(**bind):
        assert current_execution_context().run_id == (
            RUN_A if missing not in {"run_id", "all"} else ""
        )
        with pytest.raises(RunIntegrityError):
            client.set_turn()
        with pytest.raises(RunIntegrityError):
            await _complete(client)

    recorded.assert_not_awaited()
    assert client._turn.get() is None
    assert client._sequence.get() == 0


async def test_conflicting_explicit_run_id_refuses_and_never_replaces_bound_id(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """A mismatched explicit run_id is refused, not substituted.

    The rejected set_turn also cleared the stored state: a later complete
    outside canonical context has nothing to fall back to and refuses with
    zero egress (#1827 failure atomicity).
    """
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        with pytest.raises(RunIntegrityError):
            client.set_turn("run-something-else")
        assert client._turn.get() is None

    with detached_execution_context(), pytest.raises(RunIntegrityError):
        await _complete(client)

    recorded.assert_not_awaited()


# --- failure atomicity of set_turn ---------------------------------------------


async def test_valid_turn_then_invalid_set_turn_clears_the_old_state(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """An earlier valid tuple cannot remain usable after a rejected turn."""
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A)
        await _complete(client)
    recorded.assert_awaited_once()

    # The rejected set_turn happens outside any canonical context.
    with detached_execution_context():
        with pytest.raises(RunIntegrityError):
            client.set_turn(RUN_A)
        assert client._turn.get() is None
        assert client._sequence.get() == 0
        # A later complete cannot fall back to turn A: no stored turn and no
        # bound context means refusal, with zero further egress.
        with pytest.raises(RunIntegrityError):
            await _complete(client)

    recorded.assert_awaited_once()


# --- stale-turn refusal in complete --------------------------------------------


async def test_complete_after_clear_turn_and_leaving_context_refuses(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """After clear_turn and after leaving the bound context, a fresh complete
    refuses and cannot reuse the previous tuple.

    (While a complete canonical context is still live, complete adopts it —
    the documented no-prior-set_turn path — so the refusal here is asserted
    with the context gone, which is the stale-reuse case.)
    """
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A)
        await _complete(client)
        client.clear_turn()

    with pytest.raises(RunIntegrityError):
        await _complete(client)

    recorded.assert_awaited_once()


async def test_complete_after_leaving_the_context_refuses_and_cannot_reuse_tuple(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """The stored triple dies with its context; nothing resurrects it."""
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A)
        await _complete(client)
    recorded.assert_awaited_once()

    # Outside the context the stored tuple no longer matches the live one.
    with pytest.raises(RunIntegrityError):
        await _complete(client)
    recorded.assert_awaited_once()
    # The refusal also dropped the stale state: a further complete cannot
    # adopt anything.
    with detached_execution_context(), pytest.raises(RunIntegrityError):
        await _complete(client)
    recorded.assert_awaited_once()


async def test_context_moved_to_another_attempt_refuses_until_explicit_set_turn(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A)
        await _complete(client)

    # The execution moved: same Run and NodeRun, a new Attempt.
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_B):
        with pytest.raises(RunIntegrityError):
            await _complete(client)
        recorded.assert_awaited_once()

        # An explicit successful set_turn starts the new turn.
        client.set_turn(RUN_A)
        await _complete(client)
        assert recorded.await_count == 2
        assert _forwarded(recorded, 1) == (RUN_A, NODE_A, ATTEMPT_B)


# --- per-turn effect-key counter ------------------------------------------------


async def test_effect_key_starts_at_one_per_turn_and_resets_on_clear(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_turn(RUN_A)
        await _complete(client)
        await _complete(client)
        assert [call.kwargs["effect_key"] for call in recorded.call_args_list] == [
            "agent-llm-1",
            "agent-llm-2",
        ]

        client.clear_turn()
        client.set_turn(RUN_A)
        await _complete(client)
        assert recorded.call_args_list[2].kwargs["effect_key"] == "agent-llm-1"


# --- per-task identity isolation ------------------------------------------------


async def test_concurrent_tasks_sharing_one_client_keep_their_own_identity(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """Two tasks interleave set_turn and complete through one shared client.

    The barrier parks both tasks *after* both set_turns; the event then orders
    the completes A-then-B. Because turn state lives in per-client ContextVars
    (per-task context copies), neither task can observe the other's identity —
    a shared mutable instance field would make the second set_turn win and
    this test would record B's triple twice.
    """
    client, recorded = governed_client
    after_set_turn = asyncio.Barrier(2)
    a_completed = asyncio.Event()

    async def worker(
        run: str,
        node: str,
        attempt: str,
        gate: asyncio.Event | None,
        release: asyncio.Event | None,
    ) -> tuple[str, str, str]:
        with bind_execution_context(run_id=run, node_run_id=node, attempt_id=attempt):
            client.set_turn(run)
            async with after_set_turn:
                pass
            if gate is not None:
                await gate.wait()
            await _complete(client)
            if release is not None:
                release.set()
            return (run, node, attempt)

    results = await asyncio.gather(
        worker(RUN_A, NODE_A, ATTEMPT_A, None, a_completed),
        worker(RUN_B, NODE_B, ATTEMPT_B, a_completed, None),
    )

    assert results == [(RUN_A, NODE_A, ATTEMPT_A), (RUN_B, NODE_B, ATTEMPT_B)]
    assert recorded.await_count == 2
    assert _forwarded(recorded, 0) == (RUN_A, NODE_A, ATTEMPT_A)
    assert _forwarded(recorded, 1) == (RUN_B, NODE_B, ATTEMPT_B)


# --- the regression this test file exists to catch ------------------------------


async def test_identity_is_never_fabricated_when_context_is_absent(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    """No `agent-turn-…`/`agent-node-…`/`agent-attempt-…` ids may appear.

    This is the assertion the old generated-tuple behavior fails: it happily
    forwarded (`agent-turn-<hex>`, `agent-node-model`, `agent-attempt-<hex>`)
    with zero egress refusals. The refusal contract makes fabrication
    unreachable.
    """
    client, recorded = governed_client
    with detached_execution_context():
        with pytest.raises(RunIntegrityError):
            client.set_turn(None, agent_name="model")
        with pytest.raises(RunIntegrityError):
            await _complete(client)
    recorded.assert_not_awaited()
    assert all(
        "agent-turn-" not in str(call.kwargs.get("run_id", ""))
        and "agent-node-" not in str(call.kwargs.get("node_run_id", ""))
        and "agent-attempt-" not in str(call.kwargs.get("attempt_id", ""))
        for call in recorded.call_args_list
    )


@pytest.mark.parametrize("reset", ["ordinary", "clear", "rejected"])
async def test_effect_scope_is_cleared_without_changing_canonical_identity(
    governed_client: tuple[GovernedLLMClient, AsyncMock], reset: str
) -> None:
    client, recorded = governed_client
    with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
        client.set_agent_turn(agent_name="writer:with-delimiter", delegation_depth=2)
        await _complete(client)
        assert recorded.call_args.kwargs["effect_key"] == "agent-llm:writer:with-delimiter:2:1"
        assert _forwarded(recorded) == (RUN_A, NODE_A, ATTEMPT_A)
        if reset == "ordinary":
            client.set_turn()
        elif reset == "clear":
            client.clear_turn()
        else:
            with pytest.raises(RunIntegrityError):
                client.set_turn(RUN_B, agent_name="must-not-leak", delegation_depth=3)
        assert client._effect_scope.get() is None
        await _complete(client)
        assert recorded.call_args.kwargs["effect_key"] == "agent-llm-1"
        assert _forwarded(recorded, 1) == (RUN_A, NODE_A, ATTEMPT_A)


async def test_concurrent_agent_scopes_do_not_cross_tasks(
    governed_client: tuple[GovernedLLMClient, AsyncMock],
) -> None:
    client, recorded = governed_client
    ready = asyncio.Barrier(2)

    async def call(name: str, depth: int) -> None:
        with bind_execution_context(run_id=RUN_A, node_run_id=NODE_A, attempt_id=ATTEMPT_A):
            client.set_agent_turn(agent_name=name, delegation_depth=depth)
            async with ready:
                pass
            await _complete(client)
            await _complete(client)

    await asyncio.gather(call("outer", 0), call("inner", 1))
    assert {call.kwargs["effect_key"] for call in recorded.call_args_list} == {
        "agent-llm:outer:0:1",
        "agent-llm:outer:0:2",
        "agent-llm:inner:1:1",
        "agent-llm:inner:1:2",
    }
    assert all(_forwarded(recorded, index) == (RUN_A, NODE_A, ATTEMPT_A) for index in range(4))
