from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro_evolve.harness import EvalHarness
from maistro_evolve.reflect import (
    PROPOSAL_TIPS,
    _target_node,
    propose_candidates,
    reflective_improve,
)
from maistro_evolve.types import (
    DAGTopology,
    EvalResult,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)


def _node(node_id: str) -> NodeGenome:
    return NodeGenome(
        id=node_id,
        role="queen",
        strategy="react",
        model="gpt-4",
        temperature=0.3,
        max_tokens=4096,
        system_prompt="base prompt",
        max_tool_rounds=5,
    )


def _genome(
    nodes: list[NodeGenome], entry_node: str, eval_scores: dict[str, float] | None = None
) -> PipelineGenome:
    return PipelineGenome(
        id="g1",
        name="g1",
        topology=DAGTopology(
            nodes=nodes,
            edges=[],
            entry_node=entry_node,
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        eval_scores=eval_scores or {},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def test_target_node_falls_back_to_first_node_when_entry_node_id_not_found() -> None:
    genome = _genome([_node("only-node")], entry_node="missing-entry")
    assert _target_node(genome) is genome.topology.nodes[0]


@pytest.mark.asyncio
async def test_propose_candidates_reuses_tips_when_num_candidates_exceeds_tip_pool() -> None:
    genome = _genome([_node("q1")], entry_node="q1")
    node = genome.topology.nodes[0]
    counter = {"n": 0}

    async def llm_call(prompt: str, **kwargs: Any) -> str:
        counter["n"] += 1
        return f"candidate-{counter['n']}"

    candidates = await propose_candidates(
        genome, node, "proxy_ifeval", 0.4, "", llm_call, num_candidates=len(PROPOSAL_TIPS) + 2
    )

    assert len(candidates) == len(PROPOSAL_TIPS) + 2


@pytest.mark.asyncio
async def test_propose_candidates_skips_candidate_when_llm_call_raises() -> None:
    genome = _genome([_node("q1")], entry_node="q1")
    node = genome.topology.nodes[0]
    calls = {"count": 0}

    async def flaky_llm(prompt: str, **kwargs: Any) -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("llm unavailable")
        return "a working candidate"

    candidates = await propose_candidates(
        genome, node, "proxy_ifeval", 0.4, "", flaky_llm, num_candidates=2
    )

    assert candidates == ["a working candidate"]


@pytest.mark.asyncio
async def test_reflective_improve_returns_none_when_baseline_evaluation_yields_no_results() -> None:
    genome = _genome([_node("q1")], entry_node="q1", eval_scores={"proxy_ifeval": 0.4})
    harness = EvalHarness()

    async def empty_runner(g: PipelineGenome, llm_call: Any) -> EvalResult:
        raise AssertionError("not reached: evaluate_genome filters unregistered benchmarks")

    # Requesting a benchmark name that was never registered makes
    # evaluate_genome's runner-lookup silently skip it, so baseline_results
    # comes back empty and reflective_improve must return None (line 221).
    harness._benchmarks = {}

    async def llm_call(prompt: str, **kwargs: Any) -> str:
        return "irrelevant"

    outcome = await reflective_improve(genome, harness, llm_call, benchmarks=["proxy_ifeval"])

    assert outcome is None


@pytest.mark.asyncio
async def test_reflective_improve_skips_candidate_with_no_evaluation_result() -> None:
    genome = _genome([_node("q1")], entry_node="q1", eval_scores={"proxy_ifeval": 0.4})
    harness = EvalHarness()
    calls = {"count": 0}

    async def runner(g: PipelineGenome, llm_call: Any) -> EvalResult:
        calls["count"] += 1
        # Baseline rollout (proxy, non-stub score) deregisters the benchmark
        # immediately after returning, so the candidate's later call to
        # evaluate_genome finds no runner for "proxy_ifeval" and comes back empty,
        # hitting the "if not results: continue" branch (line 243).
        harness._benchmarks.pop("proxy_ifeval", None)
        return EvalResult(benchmark="proxy_ifeval", score=0.4, metadata={"fidelity": "proxy"})

    harness.register_benchmark("proxy_ifeval", runner)

    async def llm_call(prompt: str, **kwargs: Any) -> str:
        return "improved prompt"

    outcome = await reflective_improve(
        genome, harness, llm_call, benchmarks=["proxy_ifeval"], num_candidates=1
    )

    assert outcome is not None
    assert outcome.accepted is False
    assert outcome.best_candidate_score is None
