from __future__ import annotations

import sqlite3
from pathlib import Path

from .audit import GenomeAuditTrail
from .types import PipelineGenome


def _fitness_key(genome: PipelineGenome) -> float:
    """Extract the fitness score from a genome for sorting/comparison.

    Used as a key function to rank genomes by their fitness score.
    Assumes the genome has been scored (fitness_score is not None).

    Returns:
        float: The fitness score of the genome.
    """
    score = genome.fitness_score
    assert score is not None
    return score


class PopulationStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self._store: dict[str, PipelineGenome] = {}
        self._db_path: str | None
        if db_path is not None:
            self._db_path = str(db_path)
            self._init_db()
        else:
            self._db_path = None

    def _init_db(self) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS genomes (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

    def _persist(self, genome: PipelineGenome) -> None:
        if self._db_path is None:
            return
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT OR REPLACE INTO genomes (id, data) VALUES (?, ?)",
            (genome.id, genome.model_dump_json()),
        )
        conn.commit()
        conn.close()

    def _delete(self, genome_id: str) -> None:
        if self._db_path is None:
            return
        conn = sqlite3.connect(self._db_path)
        conn.execute("DELETE FROM genomes WHERE id = ?", (genome_id,))
        conn.commit()
        conn.close()

    def add(self, genome: PipelineGenome) -> None:
        self._store[genome.id] = genome
        self._persist(genome)

    def get(self, genome_id: str) -> PipelineGenome | None:
        if genome_id in self._store:
            return self._store[genome_id]
        if self._db_path is not None:
            conn = sqlite3.connect(self._db_path)
            row = conn.execute("SELECT data FROM genomes WHERE id = ?", (genome_id,)).fetchone()
            conn.close()
            if row is not None:
                genome = PipelineGenome.model_validate_json(row[0])
                self._store[genome_id] = genome
                return genome
        return None

    def list_all(self) -> list[PipelineGenome]:
        if self._db_path is not None:
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute("SELECT data FROM genomes").fetchall()
            conn.close()
            return [PipelineGenome.model_validate_json(r[0]) for r in rows]
        return list(self._store.values())

    def remove(self, genome_id: str) -> None:
        self._store.pop(genome_id, None)
        self._delete(genome_id)

    def get_champion(self) -> PipelineGenome | None:
        all_genomes = self.list_all()
        scored = [g for g in all_genomes if g.fitness_score is not None]
        if not scored:
            return None
        return max(scored, key=_fitness_key)

    def promote(self, genome_id: str) -> PipelineGenome:
        """Promote a tournament-winning genome to live traffic.

        Fail closed: a genome that has not been explicitly marked
        ``approved_for_promotion`` (a human-approval gate — see
        ``human.approve_draft``/``human.delegate_to_role`` graph nodes,
        which the caller is responsible for routing through before calling
        this) is never promoted, no matter how high its fitness/tournament
        score. Winning sandbox evaluation is necessary but not sufficient.
        """
        genome = self.get(genome_id)
        if genome is None:
            raise ValueError(f"unknown genome_id: {genome_id}")
        if not genome.approved_for_promotion:
            raise PermissionError(
                f"genome {genome_id} has not been approved for promotion "
                "(approved_for_promotion=False) — tournament/fitness wins "
                "only qualify a genome for sandbox evaluation, not live traffic"
            )
        previous = self.get_active()
        if previous is not None and previous.id != genome_id:
            previous.is_active = False
            self.add(previous)
        genome.is_active = True
        genome.rollback_target_id = previous.id if previous is not None else None
        self.add(genome)
        return genome

    def get_active(self) -> PipelineGenome | None:
        for g in self.list_all():
            if g.is_active:
                return g
        return None

    def rollback(self) -> PipelineGenome | None:
        """Roll back the currently active (promoted) genome to its predecessor.

        Returns the genome that is active after rollback (the previous
        promotion target), or ``None`` if there was nothing to roll back to.
        The regressing genome is deactivated but not deleted, so it remains
        inspectable.
        """
        active = self.get_active()
        if active is None or active.rollback_target_id is None:
            return None
        target = self.get(active.rollback_target_id)
        if target is None:
            return None
        active.is_active = False
        self.add(active)
        target.is_active = True
        self.add(target)
        return target

    async def promote_audited(self, genome_id: str, audit: GenomeAuditTrail) -> PipelineGenome:
        """Promote, with a mandatory audit record preceding and confirming
        the state change.

        The "attempt" entry is recorded before ``promote()`` runs, so a
        failing sink there blocks the mutation entirely (fail-closed,
        mirroring ``promote()``'s own approval-gate posture). The mutation
        itself can still complete before the "committed" entry is recorded
        — if logging *that* fails, the promotion is compensated (reverted
        to whichever genome was active before) and the exception re-raised,
        so the active genome can never observably change without a matching
        committed audit entry. There is no other entrypoint that can flip
        ``is_active``/promote a genome with an audit guarantee — callers
        must route every auditable promotion through this method, not
        ``promote()`` directly.
        """
        await audit.record("promotion_attempt", genome_id)
        previous = self.get_active()
        genome = self.promote(genome_id)
        try:
            await audit.record("promotion_committed", genome_id)
        except Exception:
            if previous is not None:
                self.promote(previous.id)
            else:
                genome.is_active = False
                self.add(genome)
            raise
        return genome

    async def rollback_audited(self, audit: GenomeAuditTrail) -> PipelineGenome | None:
        """Roll back, with a mandatory audit record preceding and confirming
        the state change.

        Logs the attempt (tagged with the currently-active genome, if any)
        before mutating state, then the commit (tagged with the restored
        genome, or "" if there was nothing to roll back to). If the commit
        log fails, the rollback is compensated (the regressing genome is
        reactivated, the would-be-restored genome deactivated) before
        re-raising — same no-silent-state-drift guarantee as
        ``promote_audited``.
        """
        before = self.get_active()
        await audit.record("rollback_attempt", before.id if before is not None else "")
        target = self.rollback()
        try:
            await audit.record("rollback_committed", target.id if target is not None else "")
        except Exception:
            if before is not None and target is not None:
                target.is_active = False
                self.add(target)
                before.is_active = True
                self.add(before)
            raise
        return target

    def get_lineage(self, genome_id: str) -> list[PipelineGenome]:
        chain: list[PipelineGenome] = []
        current = self.get(genome_id)
        while current is not None:
            chain.append(current)
            parent_id = current.parent_a_id
            if parent_id is None:
                break
            current = self.get(parent_id)
        return chain

    def cull_bottom(self, pct: float) -> int:
        all_genomes = self.list_all()
        scored = [g for g in all_genomes if g.fitness_score is not None]
        if not scored:
            return 0
        scored.sort(key=_fitness_key)
        cutoff = max(1, int(len(scored) * pct))
        to_remove = scored[:cutoff]
        for g in to_remove:
            self.remove(g.id)
        return len(to_remove)

    def get_breeding_pool(self, top_n: int) -> list[PipelineGenome]:
        all_genomes = self.list_all()
        scored = [g for g in all_genomes if g.fitness_score is not None]
        scored.sort(key=_fitness_key, reverse=True)
        return scored[:top_n]


class IslandPopulation:
    """FunSearch-style island model: partitions genomes into semi-isolated islands.

    Each island runs independent tournament selection. The best genome from each
    island is periodically migrated to all other islands, providing gene flow
    without collapsing diversity into a single selection pool.
    """

    def __init__(self, island_count: int = 3) -> None:
        self._island_count = max(1, island_count)
        # tournament pools (includes migrants after migration fires)
        self._islands: dict[int, list[str]] = {i: [] for i in range(self._island_count)}
        # primary island for each genome (determines child assignment)
        self._primary: dict[str, int] = {}
        self._rr: int = 0  # round-robin counter for seeds

    @property
    def island_count(self) -> int:
        return self._island_count

    def assign(self, genome: PipelineGenome) -> int:
        """Assign a genome to its island; idempotent if already assigned."""
        if genome.id in self._primary:
            return self._primary[genome.id]
        # Inherit parent's primary island so children stay with their lineage.
        if genome.parent_a_id is not None and genome.parent_a_id in self._primary:
            iid = self._primary[genome.parent_a_id]
        else:
            iid = self._rr % self._island_count
            self._rr += 1
        self._primary[genome.id] = iid
        if genome.id not in self._islands[iid]:
            self._islands[iid].append(genome.id)
        return iid

    def remove(self, genome_id: str) -> None:
        self._primary.pop(genome_id, None)
        for members in self._islands.values():
            if genome_id in members:
                members.remove(genome_id)

    def get_members(self, island_id: int) -> list[str]:
        return list(self._islands.get(island_id, []))

    def all_islands(self) -> list[int]:
        return list(self._islands.keys())

    def home_island(self, genome_id: str) -> int | None:
        return self._primary.get(genome_id)

    def force_assign(self, genome_id: str, island_id: int) -> None:
        """Place genome_id on island_id unconditionally, bypassing parent-inheritance.

        Used when the caller already knows the target island (e.g. _breed_island
        placing a child onto the island it was bred from), so that mutation
        chains that rewrite parent_a_id don't cause round-robin fallback.
        Idempotent: a genome already assigned is not moved.
        """
        if genome_id not in self._primary:
            self._primary[genome_id] = island_id
            if genome_id not in self._islands[island_id]:
                self._islands[island_id].append(genome_id)


def migrate_islands(island_pop: IslandPopulation, store: PopulationStore) -> None:
    """Share the best genome from each island into every other island's tournament pool.

    Bidirectional: best of island A → islands B, C, …; best of B → A, C, …
    The genome is shared by id (not copied), so both islands reference the same object.
    """
    best_per_island: dict[int, str | None] = {}
    for iid in island_pop.all_islands():
        scored = [
            g
            for mid in island_pop.get_members(iid)
            if (g := store.get(mid)) is not None and g.fitness_score is not None
        ]
        if scored:
            best = max(scored, key=lambda g: g.fitness_score or 0.0)
            best_per_island[iid] = best.id
        else:
            best_per_island[iid] = None

    for src_iid, best_id in best_per_island.items():
        if best_id is None:
            continue
        for dst_iid in island_pop.all_islands():
            if dst_iid == src_iid:
                continue
            dst_members = island_pop._islands[dst_iid]
            if best_id not in dst_members:
                dst_members.append(best_id)
