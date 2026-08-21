from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro_evolve.optimizer import extract_signal, optimize_topology
from maistro_evolve.types import DAGTopology, EvalResult, EvalWeights, NodeGenome, PipelineGenome


def _genome(node_id: str = "q1", entry_node: str = "q1") -> PipelineGenome:
    return PipelineGenome(
        id="test-g1",
        name="test",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id=node_id,
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node=entry_node,
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def test_extract_signal_empty_results_returns_no_eval_results_default() -> None:
    signal = extract_signal(_genome(), [])
    assert signal == {"weakest_benchmark": None, "score": 0.0, "suggestion": "no eval results"}


def test_extract_signal_picks_worst_scoring_benchmark() -> None:
    results = [
        EvalResult(benchmark="proxy_ifeval", score=0.8),
        EvalResult(benchmark="proxy_bfcl", score=0.3),
    ]
    signal = extract_signal(_genome(), results)
    assert signal["weakest_benchmark"] == "proxy_bfcl"
    assert signal["score"] == 0.3
    assert "proxy_bfcl" in signal["suggestion"]
    assert signal["weakest_node_id"] == "q1"


def test_extract_signal_falls_back_to_first_node_when_entry_node_missing() -> None:
    genome = _genome(node_id="other", entry_node="missing-entry")
    signal = extract_signal(genome, [EvalResult(benchmark="proxy_ifeval", score=0.1)])
    assert signal["weakest_node_id"] == "other"


def test_extract_signal_no_nodes_yields_none_weakest_node_id() -> None:
    genome = _genome()
    genome.topology.nodes = []
    signal = extract_signal(genome, [EvalResult(benchmark="proxy_ifeval", score=0.1)])
    assert signal["weakest_node_id"] is None


@pytest.mark.asyncio
async def test_optimize_topology_uses_llm_call_when_provided() -> None:
    async def llm_call(prompt: str) -> str:
        assert "proxy_ifeval" in prompt
        return "llm suggestion"

    signal = {"score": 0.3, "weakest_benchmark": "proxy_ifeval", "suggestion": "improve it"}
    result = await optimize_topology(_genome(), signal, llm_call=llm_call)
    assert result == {"suggestion": "llm suggestion", "source": "llm"}


@pytest.mark.asyncio
async def test_optimize_topology_falls_back_to_heuristic_when_llm_call_raises() -> None:
    async def llm_call(prompt: str) -> str:
        raise RuntimeError("boom")

    signal = {"score": 0.3, "weakest_benchmark": "proxy_ifeval"}
    result = await optimize_topology(_genome(), signal, llm_call=llm_call)
    assert result["source"] == "heuristic"
    assert "proxy_ifeval" in result["suggestion"]


@pytest.mark.asyncio
async def test_optimize_topology_falls_back_to_heuristic_when_no_llm_call() -> None:
    signal = {"score": 0.3}
    result = await optimize_topology(_genome(), signal, llm_call=None)
    assert result["source"] == "heuristic"
    assert "general" in result["suggestion"]
