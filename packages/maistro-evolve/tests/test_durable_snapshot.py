"""The domain-owned durable-snapshot choreography (#1064).

``maistro_evolve.durable_snapshot`` is the one versioned export/restore
contract the Conductor's capture and restore seams share (the capture seam at
``evolution_graph._capture_domain_snapshot``, the restart seam at
``evolution.restore_or_initialize_domain_state``). These tests pin the
choreography itself, not the per-store serializers already covered by
``test_domain_reconstruction.py``: a full round-trip through the exact
json path a durable snapshot takes, the replace-never-merge restore, the
partial-double tolerance the finalize seam relies on, and the loud failure
on malformed state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from maistro_evolve.durable_snapshot import (
    EvolveDomainExport,
    export_domain_state,
    restore_domain_state,
)
from maistro_evolve.population import PopulationStore
from maistro_evolve.tournament import EloTournament
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


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


def _seeded_domain() -> tuple[PopulationStore, EloTournament]:
    population = PopulationStore()
    population.add(_genome("g1", score=0.5))
    population.add(_genome("g2", score=0.9))
    population.record_cycle_marker("finalize:nr-9", {"status": "committed", "output": {"a": 1}})
    population.record_cycle_marker("finalize:nr-8", {"status": "faulted"})
    tournament = EloTournament(k_factor=24.0)
    tournament.record_battle(
        benchmark="proxy",
        genome_a_id="g1",
        genome_b_id="g2",
        score_a=0.9,
        score_b=0.2,
        node_run_id="nr-1",
        attempt_id="at-nr-1",
    )
    return population, tournament


def test_round_trip_matches_the_persisted_snapshot_json_path() -> None:
    population, tournament = _seeded_domain()

    export = export_domain_state(population, tournament)
    # The exact path a durable snapshot takes: pydantic/json serialization on
    # the way to the store, deserialization on the way back.
    restored_population = PopulationStore()
    restored_tournament = EloTournament()
    payload = json.loads(json.dumps(export.__dict__))
    restore_domain_state(
        restored_population,
        restored_tournament,
        EvolveDomainExport(
            genomes=payload["genomes"],
            tournament_state=payload["tournament_state"],
            cycle_markers=payload["cycle_markers"],
        ),
    )

    # Semantic equality of the whole domain, not just presence: the same
    # export captured from the restored stores is identical to the original.
    assert export_domain_state(restored_population, restored_tournament) == export
    assert restored_tournament.signature() == tournament.signature()
    # A recovered finalize sees its committed marker and returns idempotently
    # instead of re-mutating.
    assert restored_population.get_cycle_marker("finalize:nr-9") == {
        "status": "committed",
        "output": {"a": 1},
    }
    assert restored_population.get_cycle_marker("finalize:nr-8") == {"status": "faulted"}
    # The canonical publication index is what makes a replayed battle Attempt
    # a no-op; it must survive the choreography, not just the serializer.
    assert (restored_tournament.find_published_battle("nr-1", "proxy") is not None) == (
        tournament.find_published_battle("nr-1", "proxy") is not None
    )


def test_restore_replaces_prior_state_never_merges() -> None:
    population, tournament = _seeded_domain()
    export = export_domain_state(population, tournament)

    # Both stores already hold state a restart must NOT supplement with:
    # a fabricated fresh genome plus a battle the export never carried.
    target_population = PopulationStore()
    target_population.add(_genome("fabricated", score=1.0))
    target_population.record_cycle_marker("finalize:stale", {"status": "committed"})
    target_tournament = EloTournament()
    target_tournament.record_battle(
        benchmark="proxy", genome_a_id="x", genome_b_id="y", score_a=1.0, score_b=0.0
    )

    restore_domain_state(target_population, target_tournament, export)

    assert target_population.get("fabricated") is None
    assert target_population.get_cycle_marker("finalize:stale") is None
    assert target_tournament.find_published_battle("nr-1", "proxy") is not None
    assert export_domain_state(target_population, target_tournament) == export


def test_export_tolerates_a_store_without_the_marker_ledger() -> None:
    class _GenomesOnlyStore:
        """A partial double: genome export surface, no cycle-marker ledger."""

        def __init__(self, inner: PopulationStore) -> None:
            self._inner = inner

        def export_genomes_snapshot(self) -> list[str]:
            return self._inner.export_genomes_snapshot()

    population, tournament = _seeded_domain()
    # Deliberate duck-typed call: the finalize seam may capture against a
    # double that lacks the marker ledger, and a partial snapshot must stay
    # captureable rather than crash the boundary.
    export = export_domain_state(_GenomesOnlyStore(population), tournament)  # type: ignore[arg-type]
    assert export.genomes == population.export_genomes_snapshot()
    assert export.cycle_markers == {}
    assert export.tournament_state["version"] == 1


def test_malformed_tournament_state_fails_loudly_not_silently() -> None:
    population, _ = _seeded_domain()
    target_population = PopulationStore()
    target_tournament = EloTournament()
    with pytest.raises(ValueError, match="version"):
        restore_domain_state(
            target_population,
            target_tournament,
            EvolveDomainExport(
                genomes=population.export_genomes_snapshot(),
                tournament_state={"version": 99},
                cycle_markers={},
            ),
        )
