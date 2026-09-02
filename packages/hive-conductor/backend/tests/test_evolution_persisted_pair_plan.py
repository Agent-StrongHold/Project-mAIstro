"""Recovery proof for Evolve tournament execution state (#51)."""

from __future__ import annotations

from types import SimpleNamespace

from services.evolution_graph import _BattleInput, _TournamentWork


class _Genome:
    def __init__(self, genome_id: str, score: float) -> None:
        self.id = genome_id
        self.eval_scores = {"proxy": score}


class _Population:
    def __init__(self) -> None:
        self._items = {
            genome.id: genome
            for genome in (
                _Genome("g1", 0.1),
                _Genome("g2", 0.2),
                _Genome("g3", 0.3),
                _Genome("g4", 0.4),
            )
        }

    def list_all(self) -> list[_Genome]:
        return list(self._items.values())

    def get(self, genome_id: str) -> _Genome | None:
        return self._items.get(genome_id)


class _Tournament:
    def __init__(self) -> None:
        self.battles: list[tuple[str, str]] = []

    def record_battle(
        self,
        *,
        benchmark: str,
        genome_a_id: str,
        genome_b_id: str,
        score_a: float,
        score_b: float,
    ) -> None:
        self.battles.append((genome_a_id, genome_b_id))


def test_persisted_pair_output_reconstructs_each_battle_worker() -> None:
    population = _Population()
    tournament = _Tournament()
    cycle = SimpleNamespace(tournament=tournament)

    planned = _TournamentWork(cycle=cycle, population=population).prepare()
    assert planned.pair_count == 2
    assert planned.pair_index == 0

    # Each call uses a fresh worker, modeling a process/runtime reconstruction.
    first = _TournamentWork(cycle=cycle, population=population).run_pair(
        _BattleInput(pairs=planned.pairs, pair_index=planned.pair_index)
    )
    assert first.pair_index == 1
    assert first.has_more is True

    second = _TournamentWork(cycle=cycle, population=population).run_pair(
        _BattleInput.model_validate(first.model_dump())
    )
    assert second.pair_index == 2
    assert second.has_more is False
    assert len(tournament.battles) == 2
