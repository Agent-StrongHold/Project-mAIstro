"""Tests for hierarchical orchestration (SPEC-070226-c4f8 / ADR-101)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from maistro.agents.export import ExportBundle
from maistro.orchestrator.hierarchy import (
    AllHarnessesFailedError,
    ForeignHarnessError,
    HarnessAdvertisement,
    HarnessTask,
    HarnessTaskResult,
    HarnessUnavailableError,
    HierarchicalOrchestrator,
    HTTPHarnessTransport,
    InMemoryHarnessRegistry,
    LoopbackHarnessTransport,
    NoAvailableHarnessError,
)
from maistro.types.agent import AgentIdentity
from maistro.types.skill import SkillDefinition

# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


class FakeAgentSource:
    async def resolve(self, agent_name: str) -> tuple[AgentIdentity, list[SkillDefinition]]:
        identity = AgentIdentity(name=agent_name, description=f"Test agent {agent_name}")
        skills = [SkillDefinition(name="summarize", description="Summarize text")]
        return identity, skills


def advert(harness_id: str, **kwargs: Any) -> HarnessAdvertisement:
    return HarnessAdvertisement(
        harness_id=harness_id,
        endpoint=f"https://{harness_id}.local:8000",
        capabilities=("agent:run", "skill:import"),
        **kwargs,
    )


def echo_handler(harness_id: str, quality: float = 0.5) -> Any:
    async def handler(bundle: ExportBundle, task: HarnessTask) -> HarnessTaskResult:
        return HarnessTaskResult(
            harness_id=harness_id,
            task_id=task.id,
            output=f"{harness_id}:{bundle.mcp_manifest['name']}:{task.description}",
            metadata={"quality_score": quality},
        )

    return handler


def make_task() -> HarnessTask:
    return HarnessTask(id="t-1", description="do the thing", context={"k": "v"})


def make_orchestrator(
    harness_ids: list[str],
    handlers: dict[str, Any],
) -> HierarchicalOrchestrator:
    registry = InMemoryHarnessRegistry([advert(h) for h in harness_ids])
    transport = LoopbackHarnessTransport(handlers)
    return HierarchicalOrchestrator(
        registry=registry, transport=transport, agent_source=FakeAgentSource()
    )


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


class TestRegistry:
    @pytest.mark.asyncio
    async def test_list_harnesses(self) -> None:
        registry = InMemoryHarnessRegistry([advert("pi-0"), advert("openclaw-1")])
        ids = {h.harness_id for h in await registry.list_harnesses()}
        assert ids == {"pi-0", "openclaw-1"}

    @pytest.mark.asyncio
    async def test_get_harness(self) -> None:
        registry = InMemoryHarnessRegistry()
        registry.register(advert("pi-0", cost_multiplier=0.5, latency_multiplier=2.0))
        harness = await registry.get_harness("pi-0")
        assert harness.endpoint == "https://pi-0.local:8000"
        assert harness.cost_multiplier == 0.5
        assert harness.latency_multiplier == 2.0

    @pytest.mark.asyncio
    async def test_get_unknown_harness_raises_unavailable(self) -> None:
        registry = InMemoryHarnessRegistry()
        with pytest.raises(HarnessUnavailableError):
            await registry.get_harness("ghost")

    @pytest.mark.asyncio
    async def test_unregister(self) -> None:
        registry = InMemoryHarnessRegistry([advert("pi-0")])
        registry.unregister("pi-0")
        assert await registry.list_harnesses() == []


# --------------------------------------------------------------------------
# Spawn round-trip
# --------------------------------------------------------------------------


class TestSpawnOnHarness:
    @pytest.mark.asyncio
    async def test_round_trip(self) -> None:
        orch = make_orchestrator(["pi-0"], {"pi-0": echo_handler("pi-0")})
        result = await orch.spawn_on_harness("research-agent", "pi-0", make_task())
        assert result.ok
        assert result.harness_id == "pi-0"
        assert result.task_id == "t-1"
        # The exported bundle (agent name) actually reached the harness.
        assert result.output == "pi-0:research-agent:do the thing"

    @pytest.mark.asyncio
    async def test_export_bundle_is_spec_208_format(self) -> None:
        orch = make_orchestrator([], {})
        bundle = await orch.export_agent("research-agent")
        assert bundle.mcp_manifest["name"] == "research-agent"
        assert bundle.mcp_manifest["tools"][0]["name"] == "summarize"
        assert bundle.skill_md.startswith("---\n")

    @pytest.mark.asyncio
    async def test_foreign_error_propagates(self) -> None:
        async def failing(bundle: ExportBundle, task: HarnessTask) -> HarnessTaskResult:
            return HarnessTaskResult(harness_id="pi-0", task_id=task.id, error="agent exploded")

        orch = make_orchestrator(["pi-0"], {"pi-0": failing})
        with pytest.raises(ForeignHarnessError, match="agent exploded"):
            await orch.spawn_on_harness("a", "pi-0", make_task())

    @pytest.mark.asyncio
    async def test_unknown_harness_raises(self) -> None:
        orch = make_orchestrator([], {})
        with pytest.raises(HarnessUnavailableError):
            await orch.spawn_on_harness("a", "ghost", make_task())

    @pytest.mark.asyncio
    async def test_disconnected_transport_raises_unavailable(self) -> None:
        orch = make_orchestrator(["pi-0"], {})
        with pytest.raises(HarnessUnavailableError):
            await orch.spawn_on_harness("a", "pi-0", make_task())


# --------------------------------------------------------------------------
# Wave across harnesses
# --------------------------------------------------------------------------


class TestWave:
    @pytest.mark.asyncio
    async def test_wave_returns_best_of_three(self) -> None:
        orch = make_orchestrator(
            ["h-0", "h-1", "h-2"],
            {
                "h-0": echo_handler("h-0", quality=0.3),
                "h-1": echo_handler("h-1", quality=0.9),
                "h-2": echo_handler("h-2", quality=0.6),
            },
        )
        best = await orch.spawn_wave_across_harnesses(
            ["a0", "a1", "a2"], ["h-0", "h-1", "h-2"], make_task()
        )
        assert best.harness_id == "h-1"
        assert best.quality_score == 0.9

    @pytest.mark.asyncio
    async def test_wave_survives_partial_failures(self) -> None:
        orch = make_orchestrator(
            ["h-0", "h-1", "h-2"],
            {"h-1": echo_handler("h-1", quality=0.4)},  # h-0, h-2 disconnected
        )
        best = await orch.spawn_wave_across_harnesses(
            ["a0", "a1", "a2"], ["h-0", "h-1", "h-2"], make_task()
        )
        assert best.harness_id == "h-1"

    @pytest.mark.asyncio
    async def test_wave_all_failed_raises_with_failures(self) -> None:
        orch = make_orchestrator(["h-0", "h-1"], {})
        with pytest.raises(AllHarnessesFailedError) as excinfo:
            await orch.spawn_wave_across_harnesses(["a0", "a1"], ["h-0", "h-1"], make_task())
        assert len(excinfo.value.failures) == 2

    @pytest.mark.asyncio
    async def test_wave_mismatched_lengths_raises(self) -> None:
        orch = make_orchestrator([], {})
        with pytest.raises(ValueError):
            await orch.spawn_wave_across_harnesses(["a0"], ["h-0", "h-1"], make_task())


# --------------------------------------------------------------------------
# Fallback
# --------------------------------------------------------------------------


class TestFallback:
    @pytest.mark.asyncio
    async def test_fallback_skips_dead_harness(self) -> None:
        orch = make_orchestrator(
            ["h-0", "h-1"],
            {"h-1": echo_handler("h-1")},  # h-0 dead
        )
        result = await orch.spawn_with_fallback("a", ["h-0", "h-1"], make_task())
        assert result.harness_id == "h-1"

    @pytest.mark.asyncio
    async def test_fallback_all_dead_raises(self) -> None:
        orch = make_orchestrator(["h-0", "h-1"], {})
        with pytest.raises(NoAvailableHarnessError) as excinfo:
            await orch.spawn_with_fallback("a", ["h-0", "h-1"], make_task())
        assert excinfo.value.harness_ids == ["h-0", "h-1"]

    @pytest.mark.asyncio
    async def test_fallback_does_not_mask_foreign_errors(self) -> None:
        async def failing(bundle: ExportBundle, task: HarnessTask) -> HarnessTaskResult:
            return HarnessTaskResult(harness_id="h-0", task_id=task.id, error="boom")

        orch = make_orchestrator(["h-0", "h-1"], {"h-0": failing, "h-1": echo_handler("h-1")})
        with pytest.raises(ForeignHarnessError):
            await orch.spawn_with_fallback("a", ["h-0", "h-1"], make_task())

    @given(mask=st.lists(st.booleans(), min_size=1, max_size=6).filter(any))
    def test_property_spawn_succeeds_if_any_harness_available(self, mask: list[bool]) -> None:
        """SPEC property: fallback succeeds iff at least one harness is up."""
        import asyncio

        harness_ids = [f"h-{i}" for i in range(len(mask))]
        handlers = {hid: echo_handler(hid) for hid, up in zip(harness_ids, mask, strict=True) if up}
        orch = make_orchestrator(harness_ids, handlers)
        result = asyncio.run(orch.spawn_with_fallback("a", harness_ids, make_task()))
        first_up = harness_ids[mask.index(True)]
        assert result.harness_id == first_up


# --------------------------------------------------------------------------
# HTTP transport
# --------------------------------------------------------------------------


def http_transport_with(handler: Any, token: str = "secret") -> HTTPHarnessTransport:
    mock = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=mock)
    return HTTPHarnessTransport(harness_token=token, client=client)


class TestHTTPTransport:
    @pytest.mark.asyncio
    async def test_posts_bundle_and_task(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "harness_id": "pi-0",
                    "task_id": "t-1",
                    "output": "done",
                    "metadata": {"quality_score": 1.0},
                },
            )

        transport = http_transport_with(handler)
        bundle = ExportBundle(mcp_manifest={"name": "a"}, skill_md="---\n---\n")
        result = await transport.spawn(advert("pi-0"), bundle, make_task())
        assert result.ok and result.output == "done"
        assert seen["url"] == "https://pi-0.local:8000/v1/harness/sessions"
        assert seen["auth"] == "Bearer secret"
        assert seen["body"]["agent"]["mcp_manifest"] == {"name": "a"}
        assert seen["body"]["task"]["id"] == "t-1"

    @pytest.mark.asyncio
    async def test_connect_error_maps_to_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = http_transport_with(handler)
        bundle = ExportBundle(mcp_manifest={}, skill_md="")
        with pytest.raises(HarnessUnavailableError):
            await transport.spawn(advert("pi-0"), bundle, make_task())

    @pytest.mark.asyncio
    async def test_503_maps_to_unavailable(self) -> None:
        transport = http_transport_with(lambda r: httpx.Response(503))
        bundle = ExportBundle(mcp_manifest={}, skill_md="")
        with pytest.raises(HarnessUnavailableError):
            await transport.spawn(advert("pi-0"), bundle, make_task())

    @pytest.mark.asyncio
    async def test_4xx_maps_to_foreign_error(self) -> None:
        transport = http_transport_with(lambda r: httpx.Response(422, text="bad agent"))
        bundle = ExportBundle(mcp_manifest={}, skill_md="")
        with pytest.raises(ForeignHarnessError, match="bad agent"):
            await transport.spawn(advert("pi-0"), bundle, make_task())

    @pytest.mark.asyncio
    async def test_fills_missing_ids_from_context(self) -> None:
        transport = http_transport_with(lambda r: httpx.Response(200, json={"output": "x"}))
        bundle = ExportBundle(mcp_manifest={}, skill_md="")
        result = await transport.spawn(advert("pi-0"), bundle, make_task())
        assert result.harness_id == "pi-0"
        assert result.task_id == "t-1"
