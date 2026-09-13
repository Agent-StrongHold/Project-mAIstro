from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_ELO = 1200.0
_K_FACTOR = 32.0


@dataclass
class GenomeRating:
    genome_id: str
    benchmark: str
    elo: float = _DEFAULT_ELO
    wins: int = 0
    losses: int = 0
    draws: int = 0

    @property
    def total_battles(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_rate(self) -> float:
        if self.total_battles == 0:
            return 0.0
        return (self.wins + 0.5 * self.draws) / self.total_battles


@dataclass
class GenomeBattle:
    """
    Represents a battle between two genomes in a benchmark.

    Fields:
        id: Unique identifier for the battle.
        benchmark: Name of the benchmark used for the battle.
        genome_a_id: Identifier for the first genome.
        genome_b_id: Identifier for the second genome.
        winner_id: Identifier for the winning genome, or "draw" if tied.
        score_a: Score achieved by the first genome.
        score_b: Score achieved by the second genome.
        timestamp: Time when the battle was recorded.
    """

    id: int = 0
    benchmark: str = ""
    genome_a_id: str = ""
    genome_b_id: str = ""
    winner_id: str = ""
    score_a: float = 0.0
    score_b: float = 0.0
    timestamp: float = field(default_factory=time.time)


class EloTournament:
    def __init__(self, k_factor: float = _K_FACTOR, db_path: str | Path | None = None) -> None:
        self._ratings: dict[tuple[str, str], GenomeRating] = {}
        self._battles: list[GenomeBattle] = []
        self._completed_operations: set[str] = set()
        self._operation_battles: dict[str, int] = {}
        self._next_id: int = 1
        self._k_factor = k_factor
        self._db_path = str(db_path) if db_path is not None else None
        if self._db_path is not None:
            self._init_db()

    def _init_db(self) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS evolve_tournament_ratings (
                genome_id TEXT NOT NULL,
                benchmark TEXT NOT NULL,
                elo REAL NOT NULL,
                wins INTEGER NOT NULL,
                losses INTEGER NOT NULL,
                draws INTEGER NOT NULL,
                PRIMARY KEY (genome_id, benchmark)
            );
            CREATE TABLE IF NOT EXISTS evolve_tournament_battles (
                id INTEGER PRIMARY KEY,
                benchmark TEXT NOT NULL,
                genome_a_id TEXT NOT NULL,
                genome_b_id TEXT NOT NULL,
                winner_id TEXT NOT NULL,
                score_a REAL NOT NULL,
                score_b REAL NOT NULL,
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS evolve_tournament_operations (
                operation_key TEXT PRIMARY KEY,
                battle_id INTEGER NOT NULL
            );
            """
        )
        for row in conn.execute(
            "SELECT genome_id, benchmark, elo, wins, losses, draws FROM evolve_tournament_ratings"
        ):
            rating = GenomeRating(
                genome_id=row[0],
                benchmark=row[1],
                elo=row[2],
                wins=row[3],
                losses=row[4],
                draws=row[5],
            )
            self._ratings[(rating.genome_id, rating.benchmark)] = rating
        for row in conn.execute(
            "SELECT id, benchmark, genome_a_id, genome_b_id, winner_id, score_a, score_b, timestamp "
            "FROM evolve_tournament_battles ORDER BY id"
        ):
            self._battles.append(GenomeBattle(*row))
        self._operation_battles = {
            row[0]: int(row[1])
            for row in conn.execute(
                "SELECT operation_key, battle_id FROM evolve_tournament_operations"
            )
        }
        self._completed_operations = set(self._operation_battles)
        if self._battles:
            self._next_id = self._battles[-1].id + 1
        conn.close()

    def _persist_battle(self, battle: GenomeBattle, *, operation_key: str | None = None) -> None:
        if self._db_path is None:
            return
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO evolve_tournament_battles "
            "(id, benchmark, genome_a_id, genome_b_id, winner_id, score_a, score_b, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                battle.id,
                battle.benchmark,
                battle.genome_a_id,
                battle.genome_b_id,
                battle.winner_id,
                battle.score_a,
                battle.score_b,
                battle.timestamp,
            ),
        )
        if operation_key is not None:
            conn.execute(
                "INSERT OR IGNORE INTO evolve_tournament_operations (operation_key, battle_id) "
                "VALUES (?, ?)",
                (operation_key, battle.id),
            )
        for rating in self._ratings.values():
            conn.execute(
                "INSERT OR REPLACE INTO evolve_tournament_ratings "
                "(genome_id, benchmark, elo, wins, losses, draws) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    rating.genome_id,
                    rating.benchmark,
                    rating.elo,
                    rating.wins,
                    rating.losses,
                    rating.draws,
                ),
            )
        conn.commit()
        conn.close()

    def record_battle_once(
        self,
        operation_key: str,
        benchmark: str,
        genome_a_id: str,
        genome_b_id: str,
        score_a: float,
        score_b: float,
    ) -> GenomeBattle:
        """Record one logical battle at most once across process recovery."""
        if operation_key in self._completed_operations:
            battle_id = self._operation_battles[operation_key]
            for battle in reversed(self._battles):
                if battle.id == battle_id:
                    return battle
            raise RuntimeError(f"missing persisted battle for operation {operation_key!r}")
        battle = self.record_battle(
            benchmark,
            genome_a_id,
            genome_b_id,
            score_a,
            score_b,
            operation_key=operation_key,
        )
        self._completed_operations.add(operation_key)
        self._operation_battles[operation_key] = battle.id
        return battle

    def _get_rating(self, genome_id: str, benchmark: str) -> GenomeRating:
        key = (genome_id, benchmark)
        if key not in self._ratings:
            self._ratings[key] = GenomeRating(genome_id=genome_id, benchmark=benchmark)
        return self._ratings[key]

    def record_battle(
        self,
        benchmark: str,
        genome_a_id: str,
        genome_b_id: str,
        score_a: float,
        score_b: float,
        *,
        operation_key: str | None = None,
    ) -> GenomeBattle:
        if score_a > score_b:
            winner_id = genome_a_id
        elif score_b > score_a:
            winner_id = genome_b_id
        else:
            winner_id = "draw"

        battle = GenomeBattle(
            id=self._next_id,
            benchmark=benchmark,
            genome_a_id=genome_a_id,
            genome_b_id=genome_b_id,
            winner_id=winner_id,
            score_a=score_a,
            score_b=score_b,
        )
        self._next_id += 1
        self._battles.append(battle)

        ra = self._get_rating(genome_a_id, benchmark)
        rb = self._get_rating(genome_b_id, benchmark)

        expected_a = 1 / (1 + math.pow(10, (rb.elo - ra.elo) / 400))
        expected_b = 1 - expected_a

        if winner_id == genome_a_id:
            actual_a, actual_b = 1.0, 0.0
            ra.wins += 1
            rb.losses += 1
        elif winner_id == genome_b_id:
            actual_a, actual_b = 0.0, 1.0
            ra.losses += 1
            rb.wins += 1
        else:
            actual_a, actual_b = 0.5, 0.5
            ra.draws += 1
            rb.draws += 1

        ra.elo += self._k_factor * (actual_a - expected_a)
        rb.elo += self._k_factor * (actual_b - expected_b)
        self._persist_battle(battle, operation_key=operation_key)

        return battle

    def get_elo(self, genome_id: str, benchmark: str) -> float:
        return self._get_rating(genome_id, benchmark).elo

    def get_avg_elo(self, genome_id: str) -> float:
        ratings = [r for r in self._ratings.values() if r.genome_id == genome_id]
        if not ratings:
            return _DEFAULT_ELO
        return sum(r.elo for r in ratings) / len(ratings)

    def get_leaderboard(self, benchmark: str | None = None) -> list[dict[str, Any]]:
        """Ranked entries, aggregating battle counts across the matched ratings.

        Two bugs lived in the unfiltered (``benchmark=None``) path, both caused
        by looking up a rating under the literal benchmark name ``"overall"``:

        1. No battle is ever recorded against ``"overall"``, so every row
           reported ``total_battles=0`` and ``win_rate=0.0`` — a genome with a
           perfect record read as unproven. The record is now summed over the
           per-benchmark ratings that actually hold it.
        2. ``_get_rating`` *creates* a rating on miss, so simply reading the
           leaderboard inserted a phantom 1200-elo ``"overall"`` row per genome.
           ``get_avg_elo`` averages over every rating for a genome, so it then
           returned a value dragged toward the default — a read corrupting the
           number that feeds ``compute_fitness``'s elo component. Nothing here
           mutates state any more.

        With an explicit ``benchmark``, exactly one rating matches per genome
        and this reduces to the previous behaviour.
        """
        grouped: dict[str, list[GenomeRating]] = {}
        for rating in self._ratings.values():
            if benchmark is not None and rating.benchmark != benchmark:
                continue
            grouped.setdefault(rating.genome_id, []).append(rating)

        entries: list[dict[str, Any]] = []
        for gid, ratings in grouped.items():
            # A throwaway aggregate, deliberately NOT stored in _ratings; it
            # exists so total_battles/win_rate keep a single definition.
            agg = GenomeRating(
                genome_id=gid,
                benchmark=benchmark or "overall",
                elo=sum(r.elo for r in ratings) / len(ratings),
                wins=sum(r.wins for r in ratings),
                losses=sum(r.losses for r in ratings),
                draws=sum(r.draws for r in ratings),
            )
            entries.append(
                {
                    "genome_id": gid,
                    "avg_elo": round(agg.elo, 1),
                    "total_battles": agg.total_battles,
                    "win_rate": agg.win_rate,
                }
            )
        entries.sort(key=lambda e: e["avg_elo"], reverse=True)
        return entries

    def tournament_select(
        self,
        genome_ids: list[str],
        benchmark: str | None = None,
        tournament_size: int = 3,
    ) -> str | None:
        if not genome_ids:
            return None
        import random

        candidates = random.sample(genome_ids, min(tournament_size, len(genome_ids)))
        best = max(
            candidates,
            key=lambda gid: (
                self.get_avg_elo(gid) if benchmark is None else self.get_elo(gid, benchmark)
            ),
        )
        return best

    def get_battle_history(
        self,
        genome_id: str | None = None,
        benchmark: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        filtered = self._battles
        if genome_id:
            filtered = [
                b for b in filtered if b.genome_a_id == genome_id or b.genome_b_id == genome_id
            ]
        if benchmark:
            filtered = [b for b in filtered if b.benchmark == benchmark]
        return [
            {
                "id": b.id,
                "benchmark": b.benchmark,
                "genome_a": b.genome_a_id,
                "genome_b": b.genome_b_id,
                "winner": b.winner_id,
                "score_a": b.score_a,
                "score_b": b.score_b,
                "timestamp": b.timestamp,
            }
            for b in filtered[-limit:]
        ]

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_battles": len(self._battles),
            "total_genomes_rated": len({r.genome_id for r in self._ratings.values()}),
            "benchmarks_tracked": len({r.benchmark for r in self._ratings.values()}),
        }
