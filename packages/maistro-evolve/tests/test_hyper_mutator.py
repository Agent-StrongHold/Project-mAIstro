"""LLM hyper-mutator: guided typed-slot mutation with propose→verify acceptance
(ADR-070126-6386 v2). Stub LLM + stub harness — no network, no agents."""

from __future__ import annotations

import json

import pytest

from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.diversity import _random_genome
from maistro_evolve.fixer_genome import FixerGenome, render_system_prompt
from maistro_evolve.hyper_mutator import (
    build_hyper_prompt,
    hyper_mutate,
    parse_fixer_proposal,
    slot_lineage,
    spawn_fixer_challenger,
)
from maistro_evolve.types import EvalResult


def _llm(reply: str):
    async def call(prompt: str) -> str:
        return reply

    return call


class _FakeHarness:
    """evaluate_genome returns a fixed score (optionally stubbed metadata)."""

    def __init__(self, score: float, stub: bool = False) -> None:
        self.score = score
        self.stub = stub
        self.evaluated: list[str] = []

    async def evaluate_genome(self, genome, benchmarks, llm_call=None):  # type: ignore[no-untyped-def]
        self.evaluated.append(genome.id)
        return [
            EvalResult(
                benchmark=benchmarks[0],
                score=self.score,
                metadata={"stub": True} if self.stub else {},
            )
        ]


def _scored_fixer_genome(score: float = 0.5):
    g = _random_genome()
    # Pin the one slot the hyper_mutate tests below propose a value for.
    # _random_genome draws tdd_rigor as round(random.uniform(0, 1), 2) — 101
    # discrete values — and those tests propose {"tdd_rigor": 0.95}.
    # parse_fixer_proposal deliberately rejects a no-op proposal
    # (`return None if candidate == base else candidate`), so a 1-in-101
    # collision produced zero candidates and an outcome reporting the
    # misleading reason="no_candidate_beat_baseline" — a ~1%-per-run flake.
    # Per this package's CLAUDE.md: randomness is unseeded, so don't let a test
    # depend on a random draw differing from a literal.
    entry = next((n for n in g.topology.nodes if n.id == g.topology.entry_node), None)
    if entry is not None and entry.fixer is not None:
        entry.fixer.tdd_rigor = 0.10
    g.eval_scores = {"code_rsi": score}
    g.fitness_score = score * 100
    return g


# --------------------------------------------------------------------------- #
# parse_fixer_proposal
# --------------------------------------------------------------------------- #


def test_partial_proposal_merges_onto_base() -> None:
    base = FixerGenome()
    out = parse_fixer_proposal('{"test_style": "strict_tdd", "tdd_rigor": 0.9}', base)
    assert out is not None
    assert out.test_style.value == "strict_tdd"
    assert out.tdd_rigor == 0.9
    assert out.strategy == base.strategy  # omitted fields keep their value


def test_unknown_keys_ignored_and_floats_clamped() -> None:
    base = FixerGenome()
    out = parse_fixer_proposal('{"tdd_rigor": 7.5, "sparkle": true}', base)
    assert out is not None
    assert out.tdd_rigor == 1.0  # clamped into [0, 1]


def test_bad_enum_rejects_the_whole_proposal() -> None:
    assert parse_fixer_proposal('{"risk": "yolo"}', FixerGenome()) is None


def test_code_fences_and_prose_tolerated() -> None:
    reply = 'Diagnosis: too timid.\n```json\n{"risk": "bold"}\n```'
    out = parse_fixer_proposal(reply, FixerGenome())
    assert out is not None and out.risk.value == "bold"


def test_no_change_or_garbage_is_unusable() -> None:
    base = FixerGenome()
    assert parse_fixer_proposal(json.dumps({}), base) is None
    assert parse_fixer_proposal('{"risk": "balanced"}', base) is None  # identical to base
    assert parse_fixer_proposal("not json", base) is None


def test_memory_fields_are_writable() -> None:
    out = parse_fixer_proposal(
        '{"learned_failures": "docstring-only edits score poorly"}', FixerGenome()
    )
    assert out is not None
    assert out.learned_failures == "docstring-only edits score poorly"


# --------------------------------------------------------------------------- #
# spawn_fixer_challenger / slot_lineage / prompt
# --------------------------------------------------------------------------- #


def test_challenger_carries_new_fixer_and_lineage() -> None:
    g = _scored_fixer_genome()
    new_fixer = FixerGenome(goals="add real tests")
    child = spawn_fixer_challenger(g, new_fixer)
    assert child.id != g.id
    assert child.parent_a_id == g.id
    assert child.generation == g.generation + 1
    assert child.eval_scores == {}
    entry = next(n for n in child.topology.nodes if n.id == child.topology.entry_node)
    assert entry.fixer == new_fixer
    # system_prompt is re-rendered so the visible prompt can't drift from the slots.
    assert entry.system_prompt == render_system_prompt(new_fixer)
    assert child.harness_params["origin"] == "hyper_mutator"


def test_slot_lineage_walks_ancestors_worst_to_best() -> None:
    grandparent = _scored_fixer_genome(0.9)
    parent = _scored_fixer_genome(0.3)
    child = _scored_fixer_genome(0.5)
    parent.parent_a_id = grandparent.id
    child.parent_a_id = parent.id
    lineage = slot_lineage(child, [grandparent, parent, child])
    assert [round(s, 1) for _, s in lineage] == [30.0, 90.0]  # worst → best


def test_prompt_grounds_in_slots_goal_and_lineage() -> None:
    f = FixerGenome(learned_failures="avoid docstring churn")
    prompt = build_hyper_prompt(
        f,
        "code_rsi",
        0.42,
        "tip text",
        lineage=[({"risk": "bold"}, 0.2)],
        goal="produce real tests",
        preferences="never add Co-Authored-By",
    )
    assert "avoid docstring churn" in prompt
    assert "produce real tests" in prompt
    assert "never add Co-Authored-By" in prompt
    assert "0.420" in prompt
    assert "tip text" in prompt
    assert '"risk": "bold"' in prompt


# --------------------------------------------------------------------------- #
# hyper_mutate: propose→verify acceptance
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_accepts_only_a_beating_challenger() -> None:
    g = _scored_fixer_genome(0.5)
    better = _FakeHarness(score=0.8)
    out = await hyper_mutate(
        g, better, _llm('{"tdd_rigor": 0.95}'), benchmarks=["code_rsi"], num_candidates=1
    )
    assert out is not None and out.accepted
    assert out.challenger is not None
    assert out.challenger.parent_a_id == g.id

    worse = _FakeHarness(score=0.2)
    out2 = await hyper_mutate(
        g, worse, _llm('{"tdd_rigor": 0.95}'), benchmarks=["code_rsi"], num_candidates=1
    )
    assert out2 is not None and not out2.accepted
    assert out2.challenger is None
    assert out2.reason == "no_candidate_beat_baseline"


@pytest.mark.asyncio
async def test_stub_scores_are_never_accepted() -> None:
    g = _scored_fixer_genome(0.1)
    stub_harness = _FakeHarness(score=0.99, stub=True)
    out = await hyper_mutate(
        g, stub_harness, _llm('{"risk": "bold"}'), benchmarks=["code_rsi"], num_candidates=1
    )
    assert out is not None and not out.accepted  # SPEC-202: noise is not evidence


@pytest.mark.asyncio
async def test_returns_none_without_fixer_or_llm_or_score() -> None:
    g = _scored_fixer_genome(0.5)
    for n in g.topology.nodes:
        n.fixer = None
    assert await hyper_mutate(g, _FakeHarness(0.9), _llm("{}")) is None  # no fixer

    g2 = _scored_fixer_genome(0.5)
    assert await hyper_mutate(g2, _FakeHarness(0.9), None) is None  # no llm

    g3 = _random_genome()  # never evaluated — no baseline
    assert await hyper_mutate(g3, _FakeHarness(0.9), _llm("{}")) is None


@pytest.mark.asyncio
async def test_llm_errors_yield_no_candidates_not_a_crash() -> None:
    async def boom(prompt: str) -> str:
        raise RuntimeError("gateway down")

    g = _scored_fixer_genome(0.5)
    out = await hyper_mutate(g, _FakeHarness(0.9), boom, benchmarks=["code_rsi"])
    assert out is not None and out.candidate_count == 0 and not out.accepted


# --------------------------------------------------------------------------- #
# cycle routing: typed-fixer genomes go to the hyper-mutator, not reflection
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_self_improve_routes_fixer_genomes_through_hyper_mutator() -> None:
    from maistro_evolve.population import PopulationStore

    store = PopulationStore()
    g = _scored_fixer_genome(0.5)
    store.add(g)
    harness = _FakeHarness(score=0.9)
    cycle = EvolutionCycle(harness=harness)  # type: ignore[arg-type]
    cfg = EvolutionConfig(target_benchmarks=["code_rsi"], self_improve_candidates=1)

    await cycle._self_improve_top(store, cfg, _llm('{"tdd_rigor": 0.9}'))

    genomes = store.list_all()
    children = [x for x in genomes if x.harness_params.get("origin") == "hyper_mutator"]
    assert len(children) == 1  # the accepted challenger joined the population
    parent = next(x for x in genomes if x.id == g.id)
    assert parent.harness_params["last_hyper_mutation"]["accepted"] is True
    assert "hyper_history" in parent.harness_params
