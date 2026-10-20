from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from .archive import (
    CandidateArchive,
    GovernanceDecision,
    HistoricalRegressionBlocked,
    RetentionGate,
    RetentionReport,
    evaluate_retention,
    resolve_lineage,
)
from .audit import GenomeAuditTrail
from .fitness import _check_hard_gate
from .promotion import (
    PromotionPolicy,
    PromotionRecord,
    build_promotion_record,
    promotion_eligibility,
    selection_eligibility,
)
from .types import PipelineGenome

logger = logging.getLogger("maistro_evolve.population")


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
        # Decision record of the most recent committed promotion (programmatic
        # access alongside the audit-trail copy written as the committed
        # entry's detail). None until the first governed promotion commits.
        self.last_promotion_record: PromotionRecord | None = None
        # Idempotency ledger for effectful cycle-level operations (currently
        # only Evolve's canonical finalize node, #1064) keyed by a caller's
        # own logical identity (e.g. ``f"finalize:{node_run_id}"``). This is
        # deliberately process-local only, even when ``db_path`` is set: it
        # is retry evidence for an in-process Attempt retry against a NodeRun
        # that already published its mutation, not a durable cross-process
        # store. A genuine process restart has no durable population/
        # tournament state to resume against regardless (see
        # ``services.evolution_graph`` recovery resolver), so this ledger's
        # process-local scope is consistent with the rest of this store's
        # in-memory identity, not a gap this alone would need to close.
        self._cycle_markers: dict[str, dict[str, Any]] = {}

    def record_cycle_marker(self, marker_id: str, payload: dict[str, Any]) -> None:
        """Record (or overwrite) one idempotency ledger entry."""
        self._cycle_markers[marker_id] = payload

    def get_cycle_marker(self, marker_id: str) -> dict[str, Any] | None:
        return self._cycle_markers.get(marker_id)

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

    def get_champion(
        self, policy: PromotionPolicy | None = None, current_cycle: int | None = None
    ) -> PipelineGenome | None:
        """The best genome that is actually ELIGIBLE to be champion (#854).

        This used to be an unfiltered ``max`` over any genome carrying a score,
        which could return failed, unevaluated-once, stale-evidenced, or
        best-of-N-unconfirmed genomes. Selection now runs the same shared
        eligibility contract (``promotion.selection_eligibility``) that the
        promotion gate enforces — evaluated, sufficient independent samples,
        hard gate passed, objective-stamped and current evidence, uncertainty
        bounded, and fresh confirmation for best-of-N winners — so the champion
        API can never surface a candidate that the promotion gate would refuse
        on evidence grounds. (Human approval is a *promotion* gate, not a
        selection gate: dashboards may display the best evaluatable candidate,
        but only ``promote_audited`` can activate one.) When no genome is
        eligible, there is no champion — ``None``, not the least-bad genome.
        """
        pol = policy or PromotionPolicy()
        eligible = [
            g for g in self.list_all() if selection_eligibility(g, pol, current_cycle).eligible
        ]
        if not eligible:
            return None
        return max(eligible, key=_fitness_key)

    def champion_provenance(self) -> dict[str, Any] | None:
        """The verified-evidence trail behind champion selection (#384).

        ``get_champion`` picks the max-fitness genome; this method names, for
        every benchmark score that fitness rests on, the verified method that
        produced it (``eval_evidence``, folded from the runners'
        ``metadata["evidence"]``). A benchmark with no evidence record reads
        "unverified" — visible as such, never silently trusted. Returns
        ``None`` when no genome is eligible to be champion (the shared
        ``selection_eligibility`` contract, #854).
        """
        champion = self.get_champion()
        if champion is None:
            return None
        return {
            "genome_id": champion.id,
            "fitness_score": champion.fitness_score,
            "benchmarks": {
                bench: {
                    "score": champion.eval_scores.get(bench),
                    "evidence": champion.eval_evidence.get(bench, "unverified"),
                }
                for bench in sorted(champion.eval_scores)
            },
        }

    def _promote(self, genome_id: str, *, require_capability: bool = True) -> PipelineGenome:
        """The raw promotion transition: approval gate + capability gate +
        ``is_active`` flip.

        Private (#342): ``promote_audited`` is the only sanctioned public
        entrypoint, precisely so the active genome can never change without
        a matching audit record. This method (and its ``_rollback`` twin) is
        reachable only from inside the audited wrappers — including their
        compensation paths — which is what makes "a state change without an
        immutable audit record" impossible by construction rather than by
        caller discipline.

        Fail closed, twice (#342, #853):

        1. a genome that has not been explicitly marked
           ``approved_for_promotion`` (a human-approval gate — see
           ``human.approve_draft``/``human.delegate_to_role`` graph nodes,
           which the caller is responsible for routing through before calling
           this) is never promoted, no matter how high its fitness/tournament
           score. Winning sandbox evaluation is necessary but not sufficient.
        2. a genome whose *measured capability evidence* fails the correctness
           hard gates (``fitness._check_hard_gate``) is never promoted either —
           this is #853's do-nothing guard. A deliberately no-op /
           NotImplementedError-flavoured candidate has no (or failing) eval
           scores; it cannot buy promotion with missing metrics, padded cost/
           latency/Elo evidence, or an objective reweighting, because this gate
           reads the recorded scores against fixed thresholds and consults no
           weight vector at all.

        ``require_capability=False`` is ONLY for the audited compensation path
        (restoring the previously-active genome after a failed commit-log
        write): that restores an already-made promotion decision rather than
        granting a new one, and refusing the restore on evidence that decayed
        after the original promotion would strand the store mid-transition.
        The approval gate applies unconditionally in both paths.
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
        if require_capability:
            capability_ok, gate_failures = _check_hard_gate(genome)
            if not capability_ok:
                raise PermissionError(
                    f"genome {genome_id} cannot be promoted: measured "
                    f"capability evidence fails the correctness gates: "
                    f"{gate_failures} — missing metrics or reweighting cannot "
                    "clear this gate (#853)"
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

    def _rollback(self) -> PipelineGenome | None:
        """The raw rollback transition. Private for the same reason as
        ``_promote`` (#342): ``rollback_audited`` is the only sanctioned
        public entrypoint.

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

    async def promote_audited(
        self,
        genome_id: str,
        audit: GenomeAuditTrail,
        policy: PromotionPolicy | None = None,
        current_cycle: int | None = None,
        *,
        archive: CandidateArchive | None = None,
        gate: RetentionGate | None = None,
        governance: GovernanceDecision | None = None,
    ) -> PipelineGenome:
        """Promote, under the governed promotion contract (#21, #854), with a
        mandatory audit record preceding and confirming the state change.

        The governed gate (``promotion.promotion_eligibility``) runs BEFORE any
        state change: the candidate must carry sufficient independent evidence
        under a stamped objective, pass the correctness/security hard gate, be
        human-approved, and — when an incumbent is active — beat that
        incumbent's fitness by the policy's declared margin under the SAME
        objective version. A worse, unevaluated, unapproved, or
        insufficiently-supported candidate can never replace a stronger
        incumbent merely because ``promote()`` was called later; the rejection
        is recorded (``promotion_rejected`` with the reasons) and raised.

        The "attempt" entry is recorded before the raw transition runs, so a
        failing sink there blocks the mutation entirely (fail-closed,
        mirroring the transition's own approval-gate posture). The mutation
        itself can still complete before the "committed" entry is recorded
        — if logging *that* fails, the promotion is compensated (reverted
        to whichever genome was active before) and the exception re-raised,
        so the active genome can never observably change without a matching
        committed audit entry. The committed entry's detail is the full
        ``PromotionRecord`` JSON: exact candidate/incumbent ids, objective
        version, evaluation evidence (per-benchmark sample counts), decision
        rule, approval, and the resulting active version. There is no other
        entrypoint that can flip ``is_active``/promote a genome with an audit
        guarantee — the raw ``promote()``/``rollback()`` transitions this
        wraps are private (#342), so an unaudited promotion cannot be
        constructed, only forgotten.

        M4-A6 historical retention runs on this same path — there is exactly
        one promotion path, so retention cannot be bypassed by calling around
        a wrapper. With ``archive`` wired, the candidate must carry complete
        provenance and must not regress against (or skip) the prior proven
        scenario set under the declared :class:`RetentionGate` — checked
        BEFORE the attempt is recorded, so a blocked promotion writes no
        audit entries, changes no state, and lands in the archive as
        inspectable ``blocked`` evidence. Only an explicit
        :class:`GovernanceDecision` that *changes* the objective unlocks the
        block, and the governed promotion policy (approval, evidence, margin)
        still applies afterwards. ``archive=None`` preserves the exact
        pre-archive library behavior for callers that never record lineage
        (the same contract as ``EvolveCycle(archive=None)``).
        """
        pol = policy or PromotionPolicy()
        candidate = self.get(genome_id)
        retention_report = self._retention_precondition(candidate, archive, gate, governance)
        await audit.record("promotion_attempt", genome_id)
        incumbent = self.get_active()
        if candidate is None:
            detail = json.dumps(
                {
                    "candidate_id": genome_id,
                    "incumbent_id": incumbent.id if incumbent is not None else None,
                    "reasons": [f"unknown genome_id: {genome_id}"],
                },
                sort_keys=True,
            )
            await audit.record("promotion_rejected", genome_id, detail)
            raise ValueError(f"unknown genome_id: {genome_id}")
        report = promotion_eligibility(candidate, incumbent, pol, current_cycle)
        if not report.eligible:
            detail = json.dumps(
                {
                    "candidate_id": genome_id,
                    "incumbent_id": incumbent.id if incumbent is not None else None,
                    "reasons": report.reasons
                    if report is not None
                    else [f"unknown genome_id: {genome_id}"],
                    "decision_rule": {
                        "min_promotion_margin": pol.min_promotion_margin,
                        "min_samples_per_benchmark": pol.min_samples_per_benchmark,
                    },
                },
                sort_keys=True,
            )
            await audit.record("promotion_rejected", genome_id, detail)
            raise PermissionError(
                f"promotion of {genome_id} refused by the governed promotion "
                f"policy: {'; '.join(report.reasons)}"
            )
        genome = self._promote(genome_id)
        record = build_promotion_record(
            candidate=genome,
            incumbent=incumbent,
            resulting_active=genome,
            policy=pol,
            comparison=report.evidence.get("comparison", {}),
        )
        self.last_promotion_record = record
        try:
            await audit.record("promotion_committed", genome_id, record.to_json())
        except Exception:
            # Compensation restores the pre-attempt active genome — a revert of
            # an already-made decision, not a new promotion: the capability
            # re-gate is intentionally skipped (see _promote), the approval
            # gate is not.
            if incumbent is not None:
                self._promote(incumbent.id, require_capability=False)
            else:
                genome.is_active = False
                self.add(genome)
            raise
        logger.info("governed promotion committed: %s", record.summary())
        self._record_promotion_in_archive(archive, genome, retention_report)
        return genome

    def _retention_precondition(
        self,
        candidate: PipelineGenome | None,
        archive: CandidateArchive | None,
        gate: RetentionGate | None,
        governance: GovernanceDecision | None,
    ) -> RetentionReport | None:
        """The M4-A6 historical-retention precondition, run before promotion is
        even attempted.

        ``archive=None`` (or an unknown candidate) skips the check: retention
        is enforced where lineage is recorded, never faked where it is not —
        the same contract as ``EvolveCycle(archive=None)``. Otherwise the
        candidate must carry complete provenance (raises
        :class:`ProvenanceIncomplete`) and must not regress against, or skip,
        the prior proven scenario set under ``gate``: a blocked candidate is
        recorded in the archive as inspectable ``blocked`` evidence and
        :class:`HistoricalRegressionBlocked` is raised — no audit entry, no
        state change — unless ``governance`` is an explicit decision that
        *changes* the objective.
        """
        if archive is None or candidate is None:
            return None
        retention_gate = gate or RetentionGate()
        report = evaluate_retention(self, archive, candidate, retention_gate)
        if report is None or not report.blocked:
            return report
        report.governance = governance
        if retention_gate.governance_overrides(report, report.objective):
            return report
        archive.record(
            candidate,
            event="blocked",
            detail=f"promotion blocked: {report.summary()}",
        )
        raise HistoricalRegressionBlocked(report)

    def _record_promotion_in_archive(
        self,
        archive: CandidateArchive | None,
        genome: PipelineGenome,
        report: RetentionReport | None,
    ) -> None:
        """Record the promotion's provenance analysis on the archive (M4-A6).

        No-op without an archive. The promoted record carries how deep the
        recorded lineage runs (across retirement) and which archive event
        preceded this promotion — a retry after a ``blocked`` entry is exactly
        the history an auditor needs to see on the promotion record itself.
        """
        if archive is None:
            return
        lineage_depth = len(resolve_lineage(self, archive, genome.id))
        prior_event = archive.latest_event(genome.id)
        detail = f"retention: {report.summary()}" if report is not None else "no prior proven set"
        detail += f"; lineage_depth={lineage_depth}"
        if prior_event is not None:
            detail += f"; prior_archive_event={prior_event}"
        archive.record(genome, event="promoted", detail=detail)

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
        target = self._rollback()
        try:
            await audit.record("rollback_committed", target.id if target is not None else "")
        except Exception:
            if before is not None and target is not None:
                target.is_active = False
                self.add(target)
                before.is_active = True
                self.add(before)
            raise
        if target is not None and self.last_promotion_record is not None:
            # Operator context for the revert: name the governed promotion on
            # record, so an incident response can see what was last activated
            # and under which objective/decision rule.
            logger.info(
                "rollback to %s; last governed promotion on record: %s",
                target.id,
                self.last_promotion_record.summary(),
            )
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

    def cull_bottom(self, pct: float, archive: Any | None = None) -> int:
        """Remove the weakest ``pct`` of the scored population.

        With ``archive`` (a ``CandidateArchive``, typed as Any to avoid an
        import cycle — population.py is imported BY archive.py), every removed
        genome is snapshotted as ``retired`` first: culling stops being
        destruction and becomes archival (M4-A6 — retired candidates remain
        inspectable and branchable for provenance/analysis).
        """
        all_genomes = self.list_all()
        scored = [g for g in all_genomes if g.fitness_score is not None]
        if not scored:
            return 0
        scored.sort(key=_fitness_key)
        cutoff = max(1, int(len(scored) * pct))
        to_remove = scored[:cutoff]
        for g in to_remove:
            if archive is not None:
                archive.record(g, event="retired")
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
