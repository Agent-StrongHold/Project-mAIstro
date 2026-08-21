from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from maistro_evolve.benchmarks.ifeval import run_ifeval
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
from maistro_evolve.population import PopulationStore
from maistro_evolve.reflect import (
    _attribute_failure_to_node,
    build_reflection_prompt,
    reflective_improve,
    spawn_challenger,
    summarize_failures,
)
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import (
    DAGTopology,
    EvalResult,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)


def _genome(name: str = "test", prompt: str = "test") -> PipelineGenome:
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt=prompt,
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


_FAILURE_METADATA = {
    "fidelity": "proxy",
    "failures": [
        {
            "instruction": "Reply in exactly two sentences.",
            "failed_rules": ["sentence_count=2"],
            "response_excerpt": "One. Two. Three.",
            "score": 0.8,
        }
    ],
}


def _keyed_harness() -> EvalHarness:
    """Harness whose proxy_ifeval score depends on the entry prompt content."""
    harness = EvalHarness()

    async def runner(genome: PipelineGenome, llm_call: Any) -> EvalResult:
        prompt = genome.topology.nodes[0].system_prompt
        score = 0.9 if "improved" in prompt else 0.4
        return EvalResult(benchmark="proxy_ifeval", score=score, metadata=dict(_FAILURE_METADATA))

    harness.register_benchmark("proxy_ifeval", runner)
    return harness


async def _llm_improved(prompt: Any, **kwargs: Any) -> str:
    return "improved prompt"


async def _llm_worse(prompt: Any, **kwargs: Any) -> str:
    return "a different but not better prompt"


class TestReflectHelpers:
    def test_summarize_failures_formats_entries(self):
        text = summarize_failures(_FAILURE_METADATA)
        assert "Reply in exactly two sentences." in text
        assert "sentence_count=2" in text
        assert "One. Two. Three." in text

    def test_summarize_failures_empty(self):
        assert summarize_failures({}) == ""
        assert summarize_failures({"failures": []}) == ""

    def test_build_reflection_prompt_grounding(self):
        g = _genome(prompt="be helpful")
        node = g.topology.nodes[0]
        feedback = summarize_failures(_FAILURE_METADATA)
        prompt = build_reflection_prompt(g, node, "proxy_ifeval", 0.4, feedback, "Be concise.")
        assert "be helpful" in prompt  # current prompt included
        assert "instruction following" in prompt  # benchmark summary grounding
        assert "queen/react" in prompt  # topology grounding
        assert "sentence_count=2" in prompt  # failure feedback
        assert "Be concise." in prompt  # proposal tip

    def test_spawn_challenger_lineage_and_reset(self):
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        g.fitness_score = 50.0
        child = spawn_challenger(g, "q1", "improved prompt")
        assert child.id != g.id
        assert child.parent_a_id == g.id
        assert child.parent_b_id is None
        assert child.generation == g.generation + 1
        assert child.fitness_score is None
        assert child.eval_scores == {}
        assert child.harness_params["origin"] == "reflective_improve"
        assert child.topology.nodes[0].system_prompt == "improved prompt"
        # parent untouched
        assert g.topology.nodes[0].system_prompt == "test"


class TestReflectiveImprove:
    @pytest.mark.asyncio
    async def test_accepts_verified_better_candidate(self):
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4, "proxy_bfcl": 0.8}
        outcome = await reflective_improve(
            g, _keyed_harness(), _llm_improved, benchmarks=["proxy_ifeval", "proxy_bfcl"]
        )
        assert outcome is not None
        assert outcome.benchmark == "proxy_ifeval"  # weakest selected
        assert outcome.accepted is True
        assert outcome.challenger is not None
        assert outcome.challenger.parent_a_id == g.id
        assert outcome.challenger.eval_scores["proxy_ifeval"] == 0.9
        assert outcome.best_candidate_score == 0.9
        # parent prompt never mutated in place
        assert g.topology.nodes[0].system_prompt == "test"

    @pytest.mark.asyncio
    async def test_rejects_candidate_that_does_not_beat_baseline(self):
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        outcome = await reflective_improve(g, _keyed_harness(), _llm_worse)
        assert outcome is not None
        assert outcome.accepted is False
        assert outcome.challenger is None
        assert outcome.reason == "no_candidate_beat_baseline"

    @pytest.mark.asyncio
    async def test_stub_signal_never_accepted(self):
        # No runner produces a "stub" fidelity today (SPEC-202: the tier is
        # removed entirely) — but reflective_improve's guard is keyed on the
        # per-result `metadata["stub"]` flag, not on EvalHarness.fidelity, so a
        # runner can still (legitimately) flag an individual result as noise
        # (e.g. a transient gateway failure). Verify that guard directly.
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        harness = EvalHarness()
        harness._benchmarks.clear()

        async def stub_runner(genome: PipelineGenome, llm_call: Any) -> EvalResult:
            return EvalResult(benchmark="proxy_ifeval", score=0.9, metadata={"stub": True})

        harness.register_benchmark("proxy_ifeval", stub_runner)

        outcome = await reflective_improve(g, harness, _llm_improved)
        assert outcome is not None
        assert outcome.accepted is False
        assert outcome.reason == "stub_signal"
        assert outcome.candidate_count == 0  # no LLM proposals wasted on noise

    @pytest.mark.asyncio
    async def test_no_llm_or_no_scores_returns_none(self):
        g = _genome()
        assert await reflective_improve(g, _keyed_harness(), None) is None
        g2 = _genome("noscores")
        assert await reflective_improve(g2, _keyed_harness(), _llm_improved) is None

    @pytest.mark.asyncio
    async def test_outcome_summary_excludes_challenger(self):
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        outcome = await reflective_improve(g, _keyed_harness(), _llm_improved)
        assert outcome is not None
        summary = outcome.summary()
        assert "challenger" not in summary
        assert summary["accepted"] is True
        assert summary["challenger_id"] == outcome.challenger.id


class TestIfevalFailureTraces:
    @pytest.mark.asyncio
    async def test_records_failure_traces_with_llm(self):
        async def bad_llm(messages: Any, **kwargs: Any) -> str:
            return "x"

        result = await run_ifeval(_genome(), bad_llm)
        failures = result.metadata.get("failures")
        assert failures, "imperfect responses must produce failure traces"
        assert len(failures) <= 5
        for entry in failures:
            assert entry["instruction"]
            assert entry["failed_rules"]

    @pytest.mark.asyncio
    async def test_no_traces_without_llm(self):
        # No stub/heuristic fallback: an llm_call is mandatory (SPEC-202).
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_ifeval(_genome(), None)


class TestCycleIntegration:
    @pytest.mark.asyncio
    async def test_self_improve_adds_challenger_child(self):
        population = PopulationStore()
        top = _genome("top")
        # all benchmarks above hard gates so the genome can be self-improved;
        # proxy_ifeval is the weakest among target benchmarks
        top.eval_scores = {
            "proxy_ifeval": 0.4,
            "proxy_bfcl": 0.6,
            "proxy_swebench": 0.6,
            "proxy_tau_bench": 0.6,
            "proxy_gaia": 0.6,
            "proxy_ragas": 0.6,
            "proxy_terminalbench": 0.6,
            "proxy_osworld": 0.6,
        }
        top.fitness_score = 60.0
        population.add(top)
        for i in range(3):
            population.add(_genome(f"fill{i}"))

        config = EvolutionConfig(
            population_size=5,
            target_benchmarks=["proxy_ifeval"],
            self_improve=True,
            self_improve_top_n=1,
            self_improve_candidates=1,
        )
        cycle = EvolutionCycle(harness=_keyed_harness(), tournament=EloTournament())
        await cycle.run_cycle(population, llm_call=_llm_improved, config=config)

        genomes = population.list_all()
        challengers = [g for g in genomes if g.harness_params.get("origin") == "reflective_improve"]
        assert challengers, "accepted challenger must join the population"
        assert challengers[0].parent_a_id == top.id
        # champion's prompt is never overwritten in place
        surviving_top = population.get(top.id)
        assert surviving_top is not None
        assert surviving_top.topology.nodes[0].system_prompt == "test"
        reflection = surviving_top.harness_params["last_optimization"]["reflection"]
        assert reflection["accepted"] is True
        assert reflection["benchmark"] == "proxy_ifeval"


class TestOproHistory:
    def test_history_section_present_when_outcomes_exist(self):
        g = _genome(prompt="base prompt")
        node = g.topology.nodes[0]
        history = [("old prompt A", 0.3), ("old prompt B", 0.6)]
        prompt = build_reflection_prompt(g, node, "proxy_ifeval", 0.4, "", "Be concise.", history)
        assert "## Prior attempts" in prompt
        assert "score=0.300" in prompt
        assert "score=0.600" in prompt
        assert "old prompt A" in prompt
        assert "old prompt B" in prompt

    def test_history_absent_on_first_cycle(self):
        g = _genome(prompt="base prompt")
        node = g.topology.nodes[0]
        prompt_no_hist = build_reflection_prompt(g, node, "proxy_ifeval", 0.4, "", "Be concise.")
        prompt_empty = build_reflection_prompt(g, node, "proxy_ifeval", 0.4, "", "Be concise.", [])
        assert "## Prior attempts" not in prompt_no_hist
        assert "## Prior attempts" not in prompt_empty

    def test_history_sorted_ascending_by_score(self):
        g = _genome(prompt="base prompt")
        node = g.topology.nodes[0]
        # Provide history out of order — prompt must sort worst → best.
        history = [("best", 0.9), ("worst", 0.1), ("mid", 0.5)]
        prompt = build_reflection_prompt(g, node, "proxy_ifeval", 0.4, "", "Be concise.", history)
        idx_worst = prompt.index("score=0.100")
        idx_mid = prompt.index("score=0.500")
        idx_best = prompt.index("score=0.900")
        assert idx_worst < idx_mid < idx_best

    @pytest.mark.asyncio
    async def test_excerpt_set_on_accepted_outcome(self):
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        outcome = await reflective_improve(g, _keyed_harness(), _llm_improved)
        assert outcome is not None
        assert outcome.accepted is True
        assert outcome.best_candidate_prompt_excerpt is not None
        assert "improved" in outcome.best_candidate_prompt_excerpt

    @pytest.mark.asyncio
    async def test_excerpt_set_even_when_rejected(self):
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        outcome = await reflective_improve(g, _keyed_harness(), _llm_worse)
        assert outcome is not None
        assert outcome.accepted is False
        # Excerpt still populated so cycle can learn from failed attempts.
        assert outcome.best_candidate_prompt_excerpt is not None

    @pytest.mark.asyncio
    async def test_history_persisted_to_harness_params_after_cycle(self):
        population = PopulationStore()
        top = _genome("top")
        top.eval_scores = {
            "proxy_ifeval": 0.4,
            "proxy_bfcl": 0.6,
            "proxy_swebench": 0.6,
            "proxy_tau_bench": 0.6,
            "proxy_gaia": 0.6,
            "proxy_ragas": 0.6,
            "proxy_terminalbench": 0.6,
            "proxy_osworld": 0.6,
        }
        top.fitness_score = 60.0
        population.add(top)
        # Fill genomes (no eval_scores) fail the hard gate and score 0,
        # keeping top from being the culling target.
        for i in range(3):
            population.add(_genome(f"fill{i}"))

        config = EvolutionConfig(
            population_size=5,
            target_benchmarks=["proxy_ifeval"],
            self_improve=True,
            self_improve_top_n=1,
            self_improve_candidates=1,
            reflect_history_window=5,
        )
        cycle = EvolutionCycle(harness=_keyed_harness(), tournament=EloTournament())
        await cycle.run_cycle(population, llm_call=_llm_improved, config=config)

        surviving = population.get(top.id)
        assert surviving is not None
        history = surviving.harness_params.get("reflection_history", [])
        assert len(history) == 1
        benchmark, excerpt, score = history[0]
        assert isinstance(benchmark, str)
        assert isinstance(excerpt, str) and len(excerpt) <= 120
        assert isinstance(score, float)

    @pytest.mark.asyncio
    async def test_history_capped_at_window_size(self):
        population = PopulationStore()
        top = _genome("top")
        top.eval_scores = {
            "proxy_ifeval": 0.4,
            "proxy_bfcl": 0.6,
            "proxy_swebench": 0.6,
            "proxy_tau_bench": 0.6,
            "proxy_gaia": 0.6,
            "proxy_ragas": 0.6,
            "proxy_terminalbench": 0.6,
            "proxy_osworld": 0.6,
        }
        top.fitness_score = 60.0
        # Pre-seed with 5 entries (at the window limit) in (benchmark, excerpt, score) format.
        top.harness_params["reflection_history"] = [
            ("proxy_ifeval", f"old prompt {i}", 0.3 + i * 0.01) for i in range(5)
        ]
        population.add(top)
        # Fill genomes (no eval_scores) fail the hard gate and score 0,
        # keeping top from being the culling target.
        for i in range(3):
            population.add(_genome(f"fill{i}"))

        config = EvolutionConfig(
            population_size=5,
            target_benchmarks=["proxy_ifeval"],
            self_improve=True,
            self_improve_top_n=1,
            self_improve_candidates=1,
            reflect_history_window=5,
        )
        cycle = EvolutionCycle(harness=_keyed_harness(), tournament=EloTournament())
        await cycle.run_cycle(population, llm_call=_llm_improved, config=config)

        surviving = population.get(top.id)
        assert surviving is not None
        history = surviving.harness_params.get("reflection_history", [])
        assert len(history) <= 5


def _two_node_genome(entry_prompt: str = "entry prompt") -> PipelineGenome:
    """Two-node genome: entry node 'n1' + downstream node 'n2'."""
    return PipelineGenome(
        id="g-multi",
        name="multi",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="n1",
                    role="planner",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt=entry_prompt,
                    max_tool_rounds=5,
                ),
                NodeGenome(
                    id="n2",
                    role="executor",
                    strategy="chain",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="downstream prompt",
                    max_tool_rounds=5,
                ),
            ],
            edges=[],
            entry_node="n1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


class TestTextGradAttribution:
    @pytest.mark.asyncio
    async def test_attribution_targets_downstream_node_from_traces(self):
        """When LLM names the downstream node, the challenger mutates that node."""
        g = _two_node_genome()
        g.eval_scores = {"proxy_ifeval": 0.4}

        # LLM: attribution returns "n2" (downstream), proposal returns improved text.
        call_log: list[str] = []

        async def llm(prompt: Any, **_: Any) -> str:
            call_log.append(str(prompt))
            # First call (attribution) — returns downstream node id.
            if "most responsible" in str(prompt):
                return "n2"
            # Subsequent calls (proposal candidates) — return improved prompt.
            return "improved downstream prompt"

        outcome = await reflective_improve(
            g, _keyed_harness(), llm, benchmarks=["proxy_ifeval"], node_attribution=True
        )
        assert outcome is not None
        assert outcome.target_node_id == "n2"
        # Challenger's downstream node prompt was rewritten; entry node unchanged.
        if outcome.challenger is not None:
            challenger_nodes = {n.id: n for n in outcome.challenger.topology.nodes}
            assert "improved" in challenger_nodes["n2"].system_prompt
            assert challenger_nodes["n1"].system_prompt == "entry prompt"

    @pytest.mark.asyncio
    async def test_attribution_falls_back_on_unrecognised_response(self):
        """Unrecognised node id from attribution → entry node used, no error."""
        g = _two_node_genome()
        g.eval_scores = {"proxy_ifeval": 0.4}

        async def llm(prompt: Any, **_: Any) -> str:
            if "most responsible" in str(prompt):
                return "n-nonexistent"
            return "improved prompt"

        outcome = await reflective_improve(
            g, _keyed_harness(), llm, benchmarks=["proxy_ifeval"], node_attribution=True
        )
        assert outcome is not None
        assert outcome.target_node_id == "n1"  # fallback to entry node

    @pytest.mark.asyncio
    async def test_attribution_skipped_when_disabled(self):
        """node_attribution=False → attribution LLM call never made."""
        g = _two_node_genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        attribution_called = False

        async def llm(prompt: Any, **_: Any) -> str:
            nonlocal attribution_called
            if "most responsible" in str(prompt):
                attribution_called = True
                return "n2"
            return "improved prompt"

        outcome = await reflective_improve(
            g, _keyed_harness(), llm, benchmarks=["proxy_ifeval"], node_attribution=False
        )
        assert outcome is not None
        assert not attribution_called
        assert outcome.target_node_id == "n1"  # always entry node when disabled

    @pytest.mark.asyncio
    async def test_attribution_skipped_for_single_node_genome(self):
        """Single-node pipeline → attribution skipped; entry node used."""
        g = _genome()
        g.eval_scores = {"proxy_ifeval": 0.4}
        attribution_called = False

        async def llm(prompt: Any, **_: Any) -> str:
            nonlocal attribution_called
            if "most responsible" in str(prompt):
                attribution_called = True
                return "q1"
            return "improved prompt"

        outcome = await reflective_improve(
            g, _keyed_harness(), llm, benchmarks=["proxy_ifeval"], node_attribution=True
        )
        assert outcome is not None
        assert not attribution_called
        assert outcome.target_node_id == "q1"

    @pytest.mark.asyncio
    async def test_attribute_failure_to_node_returns_none_on_bad_response(self):
        """_attribute_failure_to_node returns None when LLM returns unknown id."""
        g = _two_node_genome()

        async def llm(prompt: Any, **_: Any) -> str:
            return "bogus-id"

        result = await _attribute_failure_to_node(g, "some failure trace", llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_attribute_failure_to_node_returns_valid_id(self):
        """_attribute_failure_to_node returns the node id when LLM is correct."""
        g = _two_node_genome()

        async def llm(prompt: Any, **_: Any) -> str:
            return "n2"

        result = await _attribute_failure_to_node(g, "some failure trace", llm)
        assert result == "n2"
