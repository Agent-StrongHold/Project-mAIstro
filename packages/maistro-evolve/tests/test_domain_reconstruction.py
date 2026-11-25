"""Durable reconstruction of ``EloTournament``/``PopulationStore`` (#1064).

The recovery contract requires that a genuinely new process rebuild the exact
domain state an interrupted canonical Run was admitted against. These tests
pin the serialization contract both halves depend on: an export must restore
to a semantically identical tournament (ratings, battle history, publication
index, next id), genome snapshots must round-trip byte-identically, and the
signature used by crash-vs-resume equivalence tests must be stable across a
json round-trip — the exact path a durable snapshot takes.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from maistro_evolve.population import PopulationStore
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _seeded_tournament() -> EloTournament:
    tournament = EloTournament(k_factor=24.0)
    # Three canonical battles (each with a distinct logical NodeRun) and one
    # library battle without canonical identity: the durable snapshot must
    # carry all four, and the canonical publication index must survive.
    pairs = [
        ("g1", "g2", 0.9, 0.2, "nr-1"),
        ("g2", "g3", 0.4, 0.8, "nr-2"),
        ("g1", "g3", 0.5, 0.5, "nr-3"),
    ]
    for a, b, score_a, score_b, node_run_id in pairs:
        tournament.record_battle(
            benchmark="proxy",
            genome_a_id=a,
            genome_b_id=b,
            score_a=score_a,
            score_b=score_b,
            node_run_id=node_run_id,
            attempt_id=f"at-{node_run_id}",
        )
    tournament.record_battle(
        benchmark="proxy", genome_a_id="g1", genome_b_id="g3", score_a=0.7, score_b=0.6
    )
    return tournament


def test_export_restore_round_trips_ratings_battles_and_publication_index() -> None:
    tournament = _seeded_tournament()
    snapshot = tournament.export_snapshot()
    assert snapshot["version"] == 1

    restored = EloTournament()
    restored.restore_snapshot(json.loads(json.dumps(snapshot)))

    assert restored.signature() == tournament.signature()
    assert restored.get_stats() == tournament.get_stats()
    # The canonical publication index is the idempotency key a recovered
    # battle Attempt consults: every published battle must be findable again
    # (with its Attempt identity), and the non-canonical battle must not have
    # entered the index.
    published = restored.find_published_battle("nr-1", "proxy")
    assert published is not None
    assert published.attempt_id == "at-nr-1"
    assert restored.find_published_battle("nr-2", "proxy").winner_id == "g3"
    assert restored.find_published_battle("unknown", "proxy") is None
    # The next battle id continues the restored history rather than colliding.
    follow_up = restored.record_battle(
        benchmark="proxy",
        genome_a_id="g1",
        genome_b_id="g2",
        score_a=0.1,
        score_b=0.2,
        node_run_id="nr-4",
        attempt_id="at-nr-4",
    )
    assert follow_up.id == max(b["id"] for b in tournament.export_snapshot()["battles"]) + 1
    assert restored.find_published_battle("nr-4", "proxy") is follow_up


def test_record_battle_after_replay_of_published_identity_is_a_no_op() -> None:
    """The #1064 replay contract at the domain level: same NodeRun+benchmark → same battle."""
    original = _seeded_tournament()
    restored = EloTournament()
    restored.restore_snapshot(original.export_snapshot())

    before = restored.signature()
    first = restored.find_published_battle("nr-1", "proxy")
    replayed = restored.record_battle(
        benchmark="proxy",
        genome_a_id="g1",
        genome_b_id="g2",
        score_a=0.9,
        score_b=0.2,
        node_run_id="nr-1",
        attempt_id="at-nr-1",
    )
    assert replayed is first
    # No second battle, no second counter update, no second Elo update.
    assert restored.signature() == before == original.signature()


def test_restore_rejects_unknown_snapshot_version() -> None:
    tournament = EloTournament()
    with pytest.raises(ValueError, match="version"):
        tournament.restore_snapshot({"version": 99})
    with pytest.raises(ValueError, match="version"):
        tournament.restore_snapshot({})


def _genome(genome_id: str, *, score: float | None = None) -> PipelineGenome:
    genome = PipelineGenome(
        id=genome_id,
        name=genome_id,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
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
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )
    genome.eval_scores = {"proxy": score} if score is not None else {}
    genome.harness_params["evaluation_runs"] = [
        {"run_id": "run-1", "node_run_id": f"nr-{genome_id}", "attempt_id": f"at-{genome_id}"}
    ]
    return genome


def test_population_genome_snapshot_round_trips_byte_identically() -> None:
    store = PopulationStore()
    store.add(_genome("g1", score=0.5))
    store.add(_genome("g2", score=0.9))

    genomes = store.export_genomes_snapshot()
    assert genomes == sorted(genomes)  # deterministic order

    restored = PopulationStore()
    restored.restore_genomes_snapshot(genomes)
    assert restored.export_genomes_snapshot() == genomes
    # Evaluation evidence survives: the recovered _evaluate_one consults this
    # ref to recognize an already-published evaluation.
    genome = restored.get("g1")
    assert genome is not None
    assert genome.harness_params["evaluation_runs"][0]["node_run_id"] == "nr-g1"


def test_population_cycle_markers_round_trip_for_snapshot_capture() -> None:
    store = PopulationStore()
    store.record_cycle_marker("finalize:nr-9", {"status": "committed", "output": {"a": 1}})
    markers = store.export_cycle_markers()
    restored = PopulationStore()
    restored.restore_cycle_markers(markers)
    assert restored.get_cycle_marker("finalize:nr-9") == {
        "status": "committed",
        "output": {"a": 1},
    }


def test_population_restore_rejects_malformed_genome_instead_of_dropping_it() -> None:
    store = PopulationStore()
    with pytest.raises(ValueError):
        store.restore_genomes_snapshot(["{not-json"])


def test_tournament_signature_ignores_wall_clock_but_keeps_outcomes() -> None:
    first = _seeded_tournament()
    second = _seeded_tournament()
    # Replay with fresh wall-clock timestamps: same inputs must produce the
    # same signature — the crash-vs-resume equivalence comparator.
    second.restore_snapshot(first.export_snapshot())
    second.restore_snapshot(first.export_snapshot())
    assert second.signature() == first.signature()
