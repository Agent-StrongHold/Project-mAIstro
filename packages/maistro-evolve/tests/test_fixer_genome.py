"""FixerGenome: the typed strategy-layer genome, its JSON rendering, and
serialize/crossover round-tripping through NodeGenome (ADR-070126-6386 v2)."""

from __future__ import annotations

import json

from maistro_evolve.crossover import crossover
from maistro_evolve.diversity import _random_genome
from maistro_evolve.fixer_genome import (
    FixerGenome,
    ReasoningEffort,
    random_fixer_genome,
    render_system_prompt,
    to_prompt_payload,
)
from maistro_evolve.serialize import from_json, from_yaml, to_json, to_yaml


def test_defaults_are_valid_and_bounded() -> None:
    f = FixerGenome()
    assert 0.0 <= f.minimalism <= 1.0
    assert 0.0 <= f.ambition <= 1.0
    assert 0.0 <= f.edge_focus <= 1.0
    assert 0.0 <= f.tdd_rigor <= 1.0
    assert f.reasoning_effort is None
    assert f.temperature is None
    assert f.goals == f.codebase_standards == f.learned_successes == f.learned_failures == ""


def test_random_fixer_genome_is_bounded_and_memory_is_blank() -> None:
    for _ in range(20):
        f = random_fixer_genome()
        assert 0.0 <= f.minimalism <= 1.0
        assert 0.0 <= f.ambition <= 1.0
        assert 0.0 <= f.edge_focus <= 1.0
        assert 0.0 <= f.tdd_rigor <= 1.0
        assert 0.0 <= f.temperature <= 1.0
        # Memory is learned evidence, not randomized noise — always blank at seed.
        assert f.goals == f.codebase_standards == f.learned_successes == f.learned_failures == ""


def test_payload_is_literal_json_not_prose() -> None:
    f = FixerGenome(
        goals="raise coverage on scorecard.py",
        learned_failures="don't paraphrase existing docstrings",
    )
    payload = to_prompt_payload(f)
    assert payload["goals"] == "raise coverage on scorecard.py"
    assert payload["avoid"] == "don't paraphrase existing docstrings"
    assert payload["tdd_rigor"] == f.tdd_rigor
    # Round-trips through json.dumps/loads byte-for-byte (it's a literal payload).
    assert json.loads(json.dumps(payload)) == payload


def test_blank_memory_fields_are_omitted_from_payload() -> None:
    payload = to_prompt_payload(FixerGenome())
    for key in ("goals", "codebase_standards", "learned_successes", "avoid", "strategy_hint"):
        assert key not in payload


def test_render_system_prompt_embeds_the_payload_as_json() -> None:
    f = FixerGenome(goals="ship a real test")
    rendered = render_system_prompt(f)
    # The payload is valid, parseable JSON embedded in the prompt, not paraphrased.
    start = rendered.index("{")
    embedded = json.loads(rendered[start:])
    assert embedded == to_prompt_payload(f)
    assert "ship a real test" in rendered


def test_render_is_deterministic() -> None:
    f = FixerGenome(persona="a careful reviewer")
    assert render_system_prompt(f) == render_system_prompt(f.model_copy(deep=True))


def test_reasoning_effort_enum_is_the_portable_subset() -> None:
    # low/medium/high only: OpenAI also accepts 'minimal', but other providers
    # validate the value server-side and reject it (Cerebras 400) — caught live.
    assert {e.value for e in ReasoningEffort} == {"low", "medium", "high"}


def test_legacy_minimal_migrates_to_low_on_read() -> None:
    # A population.db persisted before 'minimal' was dropped must stay loadable
    # (its whole point is lineage across runs): coerce on validation, not fail.
    f = FixerGenome.model_validate({"reasoning_effort": "minimal"})
    assert f.reasoning_effort is ReasoningEffort.LOW
    # New/portable values pass through untouched; None stays None.
    assert FixerGenome.model_validate({"reasoning_effort": "high"}).reasoning_effort.value == "high"
    assert FixerGenome.model_validate({"reasoning_effort": None}).reasoning_effort is None


def test_node_genome_fixer_round_trips_yaml_and_json() -> None:
    g = _random_genome()  # every node carries a random FixerGenome
    entry = next(n for n in g.topology.nodes if n.id == g.topology.entry_node)
    entry.fixer.goals = "round-trip me"

    reloaded_yaml = from_yaml(to_yaml(g))
    reloaded_json = from_json(to_json(g))
    for reloaded in (reloaded_yaml, reloaded_json):
        e2 = next(n for n in reloaded.topology.nodes if n.id == reloaded.topology.entry_node)
        assert e2.fixer is not None
        assert e2.fixer.goals == "round-trip me"
        assert e2.fixer.strategy == entry.fixer.strategy


def test_node_genome_without_fixer_still_round_trips() -> None:
    g = _random_genome()
    for n in g.topology.nodes:
        n.fixer = None
    reloaded = from_json(to_json(g))
    assert all(n.fixer is None for n in reloaded.topology.nodes)


def test_crossover_preserves_entry_nodes_fixer() -> None:
    a = _random_genome()
    b = _random_genome()
    a_entry = next(n for n in a.topology.nodes if n.id == a.topology.entry_node)
    a_entry.fixer.goals = "parent-a-goal"
    child = crossover(a, b)
    child_entry = next(n for n in child.topology.nodes if n.id == child.topology.entry_node)
    # crossover() deep-copies parent_a's entry node wholesale, so its fixer
    # (including learned memory) carries into the child unchanged.
    assert child_entry.fixer is not None
    assert child_entry.fixer.goals == "parent-a-goal"
