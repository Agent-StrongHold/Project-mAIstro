"""Backend selection and cross-connection identity for issue #1133."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import aiosqlite
import pytest

from maistro.capabilities import effect_context
from maistro.capabilities.binding import Binding, ResolvedBinding
from maistro.capabilities.effect_context import default_effect_context
from maistro.capabilities.invocation import Invocation, InvocationExecutionService
from maistro.capabilities.invocation_store import SqliteInvocationStore
from maistro.container import create_container
from maistro.events.envelope import EventEnvelope, SqliteEventStore
from maistro.types.config import AgentConfig


def _binding() -> Binding:
    return Binding(
        binding_id="binding-1133",
        workspace_id="workspace-1133",
        project_id="project-1133",
        node_id="node-1133",
        capability="agent.spawn_harness",
    )


@dataclass(frozen=True)
class _Provider:
    name: str = "provider-1133"
    slot: str = "agent.spawn_harness"
    trust_tier: str = "trusted"


def _invocation(invocation_id: str) -> Invocation:
    return Invocation(
        invocation_id=invocation_id,
        run_id="run-1133",
        node_run_id="node-run-1133",
        attempt_id=invocation_id,
        binding=ResolvedBinding(
            binding_id="binding-1133",
            capability="agent.spawn_harness",
            provider_name="rsi_cycle",
            provider_trust_tier="trusted",
        ),
        effect_key="dispatch:rsi_cycle",
    )


@pytest.mark.asyncio
async def test_sqlite_container_uses_one_durable_effect_event_store(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "effects.sqlite3"
    config = AgentConfig(
        router_api_key="test-key",
        database_url=f"sqlite:///{database}",
        workspace_id="workspace-1133",
    )
    first = await create_container(config)
    try:
        assert type(first.capability_effects.bindings).__name__ == "SqliteBindingStore"
        assert type(first.capability_effects.invocation_store).__name__ == "SqliteInvocationStore"
        assert isinstance(first.capability_effects.event_store, SqliteEventStore)
        assert first.capability_effects.event_store is not first.durable_event_log
        assert default_effect_context() is first.capability_effects

        await first.capability_effects.bindings.put(_binding())
        await first.capability_effects.event_store.append(
            EventEnvelope(
                type="test.effect",
                workspace_id="workspace-1133",
                run_id="run-1133",
            )
        )
    finally:
        await first.aclose()

    second = await create_container(config)
    try:
        assert await second.capability_effects.bindings.get("binding-1133") is not None
        events = await second.capability_effects.event_store.list_stream("workspace:workspace-1133")
        assert [event.type for event in events] == ["test.effect"]
    finally:
        await second.aclose()


@pytest.mark.asyncio
async def test_sqlite_racing_execution_services_dispatch_provider_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "execution-race.sqlite3"
    first_conn = await aiosqlite.connect(database)
    second_conn = await aiosqlite.connect(database)
    first_store = SqliteInvocationStore(first_conn)
    second_store = SqliteInvocationStore(second_conn)
    await first_store.ensure_schema()
    await second_store.ensure_schema()
    calls = 0

    async def resolve(_binding: Binding) -> _Provider:
        return _Provider()

    async def execute(_provider: _Provider, _request: object) -> str:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return "committed"

    try:
        outcomes = await asyncio.gather(
            InvocationExecutionService(store=first_store).invoke(
                binding=_binding(),
                run_id="run-race-1133",
                node_run_id="node-race-1133",
                attempt_id="attempt-a",
                effect_key="dispatch:once",
                request={"value": 1},
                resolver=resolve,
                executor=execute,
            ),
            InvocationExecutionService(store=second_store).invoke(
                binding=_binding(),
                run_id="run-race-1133",
                node_run_id="node-race-1133",
                attempt_id="attempt-b",
                effect_key="dispatch:once",
                request={"value": 1},
                resolver=resolve,
                executor=execute,
            ),
            return_exceptions=True,
        )
        assert any(not isinstance(outcome, BaseException) for outcome in outcomes)
        assert calls == 1
        rows = await first_store.list_effect(
            run_id="run-race-1133",
            node_run_id="node-race-1133",
            binding_id="binding-1133",
            effect_key="dispatch:once",
        )
        assert len(rows) == 1
    finally:
        await first_conn.close()
        await second_conn.close()


def test_default_effect_context_is_cached_before_container_configuration() -> None:
    """With nothing published, the ephemeral fallback is built once and reused.

    The name moved with #1133: the single `_process_effect_context` slot became
    a `_published_contexts` stack plus one `_ephemeral_context` cache, so this
    pins the cache, and the empty stack is what makes it the value under test.
    """
    published = list(effect_context._published_contexts)
    previous = effect_context._ephemeral_context
    try:
        effect_context._published_contexts.clear()
        effect_context._ephemeral_context = None
        first = default_effect_context()
        assert default_effect_context() is first
    finally:
        effect_context._ephemeral_context = previous
        effect_context._published_contexts[:] = published


@pytest.mark.asyncio
async def test_sqlite_logical_invocation_identity_rejects_two_connections(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "race.sqlite3"
    first_conn = await aiosqlite.connect(database)
    second_conn = await aiosqlite.connect(database)
    first = SqliteInvocationStore(first_conn)
    second = SqliteInvocationStore(second_conn)
    await first.ensure_schema()
    await second.ensure_schema()
    try:
        outcomes = await asyncio.gather(
            first.create(_invocation("invocation-a")),
            second.create(_invocation("invocation-b")),
            return_exceptions=True,
        )
        assert sum(not isinstance(outcome, BaseException) for outcome in outcomes) == 1
        rows = await first.list_effect(
            run_id="run-1133",
            node_run_id="node-run-1133",
            binding_id="binding-1133",
            effect_key="dispatch:rsi_cycle",
        )
        assert len(rows) == 1
    finally:
        await first_conn.close()
        await second_conn.close()


class TestTheInputEstimateIsACeiling:
    """`QuotaEstimate.maximum` is what admission holds, so it must bound.

    An under-estimate admits a call that then exceeds its budget, and the
    observation only records the overage after the provider has been paid.
    """

    @staticmethod
    def _ceiling(messages: object) -> int:
        from maistro.container import _input_token_ceiling

        return _input_token_ceiling(messages)

    def test_dense_unicode_is_not_divided_by_four(self) -> None:
        """CJK text tokenizes to far more than a quarter of its characters.

        The old `len(text) // 4` returned 5 for this input; a tokenizer can
        legitimately emit one token per character here, and often more than
        one per *byte* for rarer scripts.
        """

        text = "日本語のテキストです" * 2  # 20 characters, no ASCII

        assert self._ceiling(text) >= len(text)

    def test_every_message_is_counted_with_its_framing(self) -> None:
        """A chat request is more than the concatenation of its contents."""

        messages = [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hello"},
        ]

        bound = self._ceiling(messages)

        assert bound > len("be brief") + len("hello")

    def test_an_empty_request_still_reserves_something(self) -> None:
        """Zero is not a valid hold: the call still costs framing."""

        assert self._ceiling("") >= 1
        assert self._ceiling([]) >= 1


class TestTheCostCeilingMakesMicroUsdBudgetsUsable:
    """Without a `micro_usd` bound, a money budget refuses every call.

    `_hold_against` returns "missing upper bound for budget …" when
    `estimate.maximum(unit)` is None, so an operator who registered any
    applicable `micro_usd` budget had every governed invocation denied — the
    advertised cost unit could not be used at all.
    """

    class _Registry:
        """A registry with one priced model, like a configured deployment."""

        def __init__(self, **rates: float) -> None:
            self._rates = rates

        async def get_model(self, name: str) -> object:
            if name != "priced-model":
                raise KeyError(name)
            return SimpleNamespace(**self._rates)

    @staticmethod
    async def _ceiling(registry: object, **kwargs: object) -> int | None:
        from maistro.container import _cost_ceiling_micro_usd

        return await _cost_ceiling_micro_usd(registry, **kwargs)  # type: ignore[arg-type]

    async def test_a_priced_model_yields_a_bound(self) -> None:
        registry = self._Registry(cost_per_1k_input=1.0, cost_per_1k_output=3.0)

        bound = await self._ceiling(
            registry, model="priced-model", input_tokens=1000, output_tokens=1000
        )

        # 1 cent + 3 cents = 4 cents = 40_000 micro-USD.
        assert bound == 40_000

    async def test_the_bound_rounds_up_never_down(self) -> None:
        """A hold smaller than the spend it holds against is not a hold."""

        registry = self._Registry(cost_per_1k_input=1.0, cost_per_1k_output=0.0)

        bound = await self._ceiling(registry, model="priced-model", input_tokens=1, output_tokens=0)

        assert bound == 10  # 0.001 cents rounds up to 10 micro-USD, not 0

    async def test_an_unpriced_model_stays_unknown_rather_than_guessing(self) -> None:
        """A money budget cannot admit a call whose price nobody knows.

        `None` refuses; an invented number would admit the call against a
        ceiling that does not exist.
        """

        registry = self._Registry(cost_per_1k_input=1.0, cost_per_1k_output=1.0)

        assert (
            await self._ceiling(registry, model="unknown-model", input_tokens=10, output_tokens=10)
            is None
        )
        assert (
            await self._ceiling(None, model="priced-model", input_tokens=10, output_tokens=10)
            is None
        )
