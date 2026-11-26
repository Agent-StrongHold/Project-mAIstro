"""Immutable candidate archive + historical-retention evaluation (M4-A6).

Two concerns, one module, because they are two halves of one rule: **a gain
must never silently erase historical capability.**

*The archive* is the immutable, append-only ledger of candidate snapshots.
Every candidate is snapshotted when it is created and again when it is retired
(culled), so lineage survives population turnover and any archived candidate —
champion or failed stepping stone — can be branched from later (the Darwin
Gödel Machine archive/stepping-stone design: yesterday's dead end is often
tomorrow's path). Retired candidates stay inspectable forever; nothing in this
module deletes an entry.

*The retention gate* enforces the anti-forgetting contract at the only seam
that matters — promotion. Before a candidate is promoted, the prior proven
scenario set (the scenarios on which previously proven candidates scored,
under the same objective) is replayed — or a declared deterministic sample of
it — and any historical regression blocks promotion, unless an explicit
:class:`GovernanceDecision` changes the objective. A governance decision that
re-asserts the same objective overrides nothing.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from .types import CandidateProvenance, PipelineGenome

if TYPE_CHECKING:
    # Import-time cycle guard: population → fitness → diversity → mutate →
    # archive (M4-A6 provenance stamping) forms a loop once #853 made the
    # population own the objective. PopulationStore is only needed here for
    # type annotations, which are strings under `from __future__ import
    # annotations` — the runtime import stays lazy.
    from .population import PopulationStore


class OperatorKind(StrEnum):
    """The operator that produced a candidate. Stored as its string value on
    :class:`maistro_evolve.types.CandidateProvenance`."""

    SEED = "seed"
    TOPOLOGY_MUTATION = "topology_mutation"
    NODE_MUTATION = "node_mutation"
    PROMPT_MUTATION = "prompt_mutation"
    FIXER_MUTATION = "fixer_mutation"
    ALL_MUTATION = "all_mutation"
    CROSSOVER = "crossover"
    REFLECTION = "reflection"
    HYPER_MUTATION = "hyper_mutation"
    ARCHIVE_BRANCH = "archive_branch"


class ProvenanceIncomplete(RuntimeError):
    """A candidate record does not identify what M4-A6 requires.

    Raised by :func:`complete_provenance` — the fail-closed check the
    promotion gate runs before anything else: a candidate that cannot say
    which operator produced it, under what objective, and at what prompt
    version must not be promotable, because its provenance cannot be audited
    after the fact.
    """


class HistoricalRegressionBlocked(RuntimeError):
    """Promotion was blocked because the candidate regressed against the
    prior proven scenario set (or never replayed it). Carries the
    :class:`RetentionReport` as ``.report`` for callers that surface *why*.
    """

    def __init__(self, report: RetentionReport) -> None:
        super().__init__(f"historical regression blocked promotion: {report.summary()}")
        self.report = report


class GovernanceDecision(BaseModel):
    """An explicit decision to change the objective, unlocking a promotion
    that the retention gate would otherwise block.

    The override is valid only when ``new_objective`` is non-empty and differs
    from the objective the historical evidence was proven under — re-asserting
    the same objective in governance clothing is still a blocked promotion.
    """

    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    rationale: str
    decided_by: str
    new_objective: str
    decided_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class RetentionPolicy(BaseModel):
    """The *declared* policy for how the prior proven scenario set is
    re-checked before promotion.

    ``replay`` re-checks every proven scenario; ``sample`` re-checks a
    deterministic sample (stable for a given scenario set, so two evaluations
    of the same population state always compare the same scenarios).
    ``regression_tolerance`` is how far below the historical best a candidate
    may fall on a scenario before it counts as a regression.
    """

    mode: Literal["replay", "sample"] = "replay"
    sample_size: int = Field(default=5, ge=1)
    regression_tolerance: float = Field(default=0.0, ge=0.0, le=1.0)


class RetentionOutcome(BaseModel):
    scenario: str
    status: Literal["pass", "regressed", "not_evaluated"]
    historical_score: float
    candidate_score: float | None = None


class RetentionReport(BaseModel):
    """The outcome of one retention evaluation of one candidate."""

    policy_mode: str
    objective: str
    scenarios: list[RetentionOutcome] = Field(default_factory=list)
    governance: GovernanceDecision | None = None
    blocked: bool = False

    @property
    def regressed(self) -> list[str]:
        return [o.scenario for o in self.scenarios if o.status == "regressed"]

    @property
    def not_evaluated(self) -> list[str]:
        return [o.scenario for o in self.scenarios if o.status == "not_evaluated"]

    def summary(self) -> str:
        parts = [f"mode={self.policy_mode}", f"blocked={self.blocked}"]
        # Regressions render with their evidence — the candidate score against
        # the historical best it fell short of — so the blocked-promotion audit
        # record (archive detail, exception message) states WHY, not just WHICH.
        if self.regressed:
            parts.extend(
                f"regressed {outcome.scenario}: candidate "
                f"{outcome.candidate_score:.4f} < proven "
                f"{outcome.historical_score:.4f}"
                for outcome in self.scenarios
                if outcome.status == "regressed"
            )
        if self.not_evaluated:
            parts.append(f"not_evaluated={','.join(self.not_evaluated)}")
        if self.governance is not None:
            parts.append(
                f"governance={self.governance.decision_id} by {self.governance.decided_by}"
            )
        return "; ".join(parts)


class ArchiveEntry(BaseModel):
    """One immutable archive snapshot: the candidate as it was at ``recorded_at``."""

    record_id: str
    candidate: PipelineGenome
    # "blocked" = promotion refused by the retention gate (the candidate stays
    # live in the population — distinct from "retired", which records an
    # actual cull/removal).
    event: Literal["created", "retired", "promoted", "branched", "blocked"]
    recorded_at: str
    detail: str = ""


def prompt_version(genome: PipelineGenome) -> str:
    """Content version of the candidate's evolvable prompt/template material.

    A deterministic 12-hex digest over every node's (role, model, strategy,
    system_prompt, fixer slots) — the same immutable template-version
    semantics the rest of the repo applies to templates: equal content means
    equal version, any change to the evolvable prompt material means a new
    one. Sampling knobs (temperature/max_tokens) and eval weights are
    deliberately excluded: they are not template content.
    """
    hasher = hashlib.sha256()
    for node in genome.topology.nodes:
        hasher.update(node.role.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(node.model.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(node.strategy.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(node.system_prompt.encode("utf-8"))
        hasher.update(b"\x00")
        if node.fixer is not None:
            hasher.update(node.fixer.model_dump_json().encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()[:12]


def stamp_provenance(
    genome: PipelineGenome,
    *,
    parents: list[str],
    operator: OperatorKind | str,
    base: PipelineGenome | None = None,
    objective: str | None = None,
    detail: str = "",
) -> PipelineGenome:
    """Stamp (or restamp) ``genome``'s candidate record in place and return it.

    ``objective`` defaults to inheriting the first parent's recorded objective
    (the objective a candidate was bred under does not change by being
    mutated); pass it explicitly to record a new one. ``prompt_version`` is
    always recomputed from the candidate's actual content — never inherited —
    so it cannot drift from what the candidate really carries.

    The legacy ``parent_a_id``/``parent_b_id`` fields are derived here from the
    authoritative ``parents`` record, so the two lineage encodings cannot
    drift apart: every producer gets both for free, and a composite producer
    (crossover + mutate) does not have to remember to re-point them at the
    stored parents after re-stamping.
    """
    inherited = base.provenance if base is not None else None
    resolved_objective = (
        objective if objective is not None else (inherited.objective if inherited else "")
    )
    if parents:
        genome.parent_a_id = parents[0]
    genome.parent_b_id = parents[1] if len(parents) > 1 else None
    genome.provenance = CandidateProvenance(
        parents=list(parents),
        operator=operator.value if isinstance(operator, OperatorKind) else operator,
        objective=resolved_objective,
        prompt_version=prompt_version(genome),
        evaluation_run_ids=list(inherited.evaluation_run_ids) if inherited else [],
        detail=detail,
    )
    return genome


def apply_objective(genome: PipelineGenome, objective: str) -> PipelineGenome:
    """Record ``objective`` on an already-stamped candidate (no-op when empty)."""
    if not objective:
        return genome
    base = genome.provenance or CandidateProvenance()
    genome.provenance = base.model_copy(update={"objective": objective})
    return genome


def evaluation_run_ids(genome: PipelineGenome) -> list[str]:
    """Canonical evaluation Run ids this candidate carries evidence for.

    Folds the candidate's own ``provenance.evaluation_run_ids`` together with
    the execution refs the canonical graph path appends to
    ``harness_params["evaluation_runs"]`` (see services.evolution_graph's
    ``_append_execution_ref``), deduplicated, order-preserving.
    """
    ids: list[str] = []
    if genome.provenance is not None:
        ids.extend(genome.provenance.evaluation_run_ids)
    for ref in genome.harness_params.get("evaluation_runs", []):
        if isinstance(ref, dict):
            run_id = str(ref.get("run_id") or "")
            if run_id and run_id not in ids:
                ids.append(run_id)
    return ids


def complete_provenance(genome: PipelineGenome) -> CandidateProvenance:
    """Return the candidate's provenance, or raise :class:`ProvenanceIncomplete`.

    A complete record identifies the producing operator, the source objective,
    and the prompt/template content version. Parents may legitimately be empty
    (a seed); evaluation evidence is *not* checked here — that is the
    retention gate's job, per scenario.
    """
    prov = genome.provenance
    missing = []
    if prov is None:
        missing.append("provenance record")
    else:
        if not prov.operator:
            missing.append("operator")
        if not prov.objective:
            missing.append("objective")
        if not prov.prompt_version:
            missing.append("prompt_version")
    if missing:
        raise ProvenanceIncomplete(
            f"candidate {genome.id} cannot be promoted: its record does not "
            f"identify {', '.join(missing)} (M4-A6 provenance is mandatory "
            "for promotion)"
        )
    assert prov is not None
    return prov


class CandidateArchive:
    """Append-only ledger of immutable candidate snapshots.

    Every entry is a deep copy taken at ``record`` time, so later mutation of
    the live genome can never rewrite history. Snapshots survive population
    turnover: ``PopulationStore.cull_bottom(archive=...)`` records a
    ``retired`` entry before removing a genome, and retirement is *queryable*
    (``list_retired``) and *resumable* (``branch``) forever.

    ``db_path`` optionally mirrors entries into SQLite (same optional-
    persistence posture as ``PopulationStore``); existing entries are loaded
    at construction so a restarted process sees the same ledger.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._entries: list[ArchiveEntry] = []
        self._db_path: str | None = None
        if db_path is not None:
            self._db_path = str(db_path)
            self._init_db()
            self._load()

    def _init_db(self) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS candidate_archive (
                record_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                event TEXT NOT NULL,
                data TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_candidate_archive_candidate "
            "ON candidate_archive (candidate_id)"
        )
        conn.commit()
        conn.close()

    def _load(self) -> None:
        assert self._db_path is not None
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute("SELECT data FROM candidate_archive ORDER BY rowid").fetchall()
        conn.close()
        self._entries = [ArchiveEntry.model_validate_json(r[0]) for r in rows]

    def record(
        self,
        genome: PipelineGenome,
        event: Literal["created", "retired", "promoted", "branched", "blocked"],
        detail: str = "",
    ) -> ArchiveEntry:
        """Snapshot ``genome`` under ``event``. The snapshot folds the
        candidate's current evaluation-Run evidence into its provenance record
        so the archived candidate identifies its evaluation Runs on its own."""
        snapshot = genome.model_copy(deep=True)
        run_ids = evaluation_run_ids(snapshot)
        if snapshot.provenance is not None and run_ids != snapshot.provenance.evaluation_run_ids:
            snapshot.provenance = snapshot.provenance.model_copy(
                update={"evaluation_run_ids": run_ids}
            )
        entry = ArchiveEntry(
            record_id=uuid.uuid4().hex[:16],
            candidate=snapshot,
            event=event,
            recorded_at=datetime.now(UTC).isoformat(),
            detail=detail,
        )
        self._entries.append(entry)
        if self._db_path is not None:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "INSERT OR REPLACE INTO candidate_archive "
                "(record_id, candidate_id, event, data) VALUES (?, ?, ?, ?)",
                (
                    entry.record_id,
                    entry.candidate.id,
                    entry.event,
                    entry.model_dump_json(),
                ),
            )
            conn.commit()
            conn.close()
        return entry

    def entries_for(self, candidate_id: str) -> list[ArchiveEntry]:
        """Every snapshot of one candidate, in append order — the candidate's
        full recorded lifecycle."""
        return [e for e in self._entries if e.candidate.id == candidate_id]

    def _latest(self, candidate_id: str) -> ArchiveEntry | None:
        entries = self.entries_for(candidate_id)
        return entries[-1] if entries else None

    def get(self, candidate_id: str) -> PipelineGenome | None:
        """Latest snapshot of a candidate, or ``None`` — even after it has
        been retired from the live population."""
        entry = self._latest(candidate_id)
        return entry.candidate if entry is not None else None

    def candidates(self) -> list[str]:
        """Every candidate id ever recorded, in first-seen order."""
        seen: list[str] = []
        for entry in self._entries:
            if entry.candidate.id not in seen:
                seen.append(entry.candidate.id)
        return seen

    def latest_event(self, candidate_id: str) -> str | None:
        entry = self._latest(candidate_id)
        return entry.event if entry is not None else None

    def branch(
        self,
        candidate_id: str,
        *,
        objective: str | None = None,
        detail: str = "",
    ) -> PipelineGenome:
        """Derive a fresh candidate from any archived candidate — champion,
        retired, or a failed stepping stone. Non-champion branching is the
        point: the archive exists precisely so a lineage can restart from a
        candidate the cull would otherwise have erased.

        The child gets a new id, records the archived candidate as its parent
        with the ``archive_branch`` operator, inherits the archived
        candidate's objective (unless overridden) and generation + 1, and
        starts with a clean evaluation slate — its evaluation evidence must be
        its own.
        """
        source_entry = self._latest(candidate_id)
        if source_entry is None:
            raise KeyError(f"cannot branch: candidate {candidate_id!r} is not in the archive")
        source = source_entry.candidate
        now = datetime.now(UTC).isoformat()
        child = source.model_copy(deep=True)
        child.id = uuid.uuid4().hex[:12]
        child.name = f"branch-{source.id[:6]}"
        child.generation = source.generation + 1
        child.fitness_score = None
        child.eval_scores = {}
        child.harness_params = {"origin": "archive_branch"}
        child.is_active = False
        child.rollback_target_id = None
        child.created_at = now
        child.updated_at = now
        stamp_provenance(
            child,
            parents=[source.id],
            operator=OperatorKind.ARCHIVE_BRANCH,
            base=source,
            objective=objective,
            detail=detail,
        )
        # The default detail pins WHICH snapshot was branched from (a candidate
        # accumulates several over its lifecycle) and whether it was retired —
        # branching from a retired stepping stone is the DGM stepping-stone
        # move, and the provenance of that move is the point.
        self.record(
            child,
            event="branched",
            detail=detail
            or (
                f"branched from {source.id} snapshot {source_entry.recorded_at}"
                f" ({source_entry.event})"
            ),
        )
        return child

    def __len__(self) -> int:
        return len(self._entries)


def resolve_lineage(
    population: PopulationStore,
    archive: CandidateArchive,
    genome_id: str,
) -> list[PipelineGenome]:
    """Full ancestor chain of ``genome_id``, surviving retirement.

    ``PopulationStore.get_lineage`` walks only live genomes, so a culled
    parent truncates a candidate's history exactly when history matters most.
    This walks the same chain but falls back to the archive's latest snapshot
    when a parent is no longer live, so recorded lineage is immutable evidence
    rather than an artifact of current population state. BOTH recorded parents
    are walked (A-lineage first, then B-lineage — crossover children name two
    parents), guarded against lineage cycles; unrecorded ancestors are
    dropped without raising.
    """
    chain: list[PipelineGenome] = []
    visited: set[str] = set()
    frontier: list[str] = [genome_id]
    while frontier:
        current_id = frontier.pop(0)
        if current_id in visited:
            continue
        visited.add(current_id)
        current: PipelineGenome | None = population.get(current_id)
        if current is None:
            current = archive.get(current_id)
        if current is None:
            continue
        chain.append(current)
        if current.parent_a_id:
            frontier.append(current.parent_a_id)
        if current.parent_b_id:
            frontier.append(current.parent_b_id)
    return chain


class RetentionGate:
    """Evaluates a candidate against the prior proven scenario set under a
    declared :class:`RetentionPolicy`."""

    def __init__(self, policy: RetentionPolicy | None = None) -> None:
        self.policy = policy or RetentionPolicy()

    def select_scenarios(self, proven_scores: dict[str, float]) -> list[str]:
        """The scenarios this policy re-checks, deterministically.

        ``replay`` is every proven scenario. ``sample`` draws the declared
        sample size by ranking the scenarios on a digest keyed to the whole
        proven set, so the same proven set always samples the same scenarios
        (two evaluations of one population state must be comparable — an
        arbitrary sample would make "no regression" a coin flip). The digest
        is a pure function of the scenario set: no clock, no process-level
        RNG state, hence reproducible across runs and hosts.
        """
        names = sorted(proven_scores)
        if self.policy.mode == "replay" or len(names) <= self.policy.sample_size:
            return names
        seed_material = "\n".join(names).encode("utf-8")
        ranked = sorted(
            names,
            key=lambda name: (
                hashlib.sha256(seed_material + b"\x00" + name.encode("utf-8")).digest(),
                name,
            ),
        )
        return sorted(ranked[: self.policy.sample_size])

    def evaluate(
        self,
        candidate: PipelineGenome,
        proven_scores: dict[str, float],
        scenarios: list[str] | None = None,
    ) -> RetentionReport:
        """Compare the candidate's current eval evidence against the
        historical best on each selected scenario.

        A scenario the candidate never scored is ``not_evaluated`` and blocks:
        a retention policy that did not require the challenger to actually
        face the proven set would make replay a paperwork exercise.
        """
        outcomes: list[RetentionOutcome] = []
        objective = candidate.provenance.objective if candidate.provenance else ""
        for scenario in scenarios or self.select_scenarios(proven_scores):
            score = candidate.eval_scores.get(scenario)
            historical = proven_scores[scenario]
            if score is None:
                outcomes.append(
                    RetentionOutcome(
                        scenario=scenario,
                        status="not_evaluated",
                        historical_score=historical,
                    )
                )
            elif score < historical - self.policy.regression_tolerance:
                outcomes.append(
                    RetentionOutcome(
                        scenario=scenario,
                        status="regressed",
                        historical_score=historical,
                        candidate_score=score,
                    )
                )
            else:
                outcomes.append(
                    RetentionOutcome(
                        scenario=scenario,
                        status="pass",
                        historical_score=historical,
                        candidate_score=score,
                    )
                )
        blocked = any(o.status in ("regressed", "not_evaluated") for o in outcomes)
        return RetentionReport(
            policy_mode=self.policy.mode,
            objective=objective,
            scenarios=outcomes,
            blocked=blocked,
        )

    def governance_overrides(self, report: RetentionReport, historical_objective: str) -> bool:
        """Whether the report's governance decision validly unlocks a blocked
        promotion: only an explicit decision that *changes* the objective does.
        """
        gov = report.governance
        if gov is None:
            return False
        return bool(gov.new_objective) and gov.new_objective != historical_objective


def _population_plus_archive(
    population: PopulationStore,
    archive: CandidateArchive,
) -> dict[str, PipelineGenome]:
    """The live population overlaid with archive snapshots for ids no longer
    live — every candidate whose recorded evidence still counts (M4-A6: a
    culled stepping stone defends its scenarios as well as a champion)."""
    seen = {genome.id: genome for genome in population.list_all()}
    for candidate_id in archive.candidates():
        if candidate_id not in seen:
            snapshot = archive.get(candidate_id)
            if snapshot is not None:
                seen[candidate_id] = snapshot
    return seen


def proven_scenario_scores(
    population: PopulationStore,
    archive: CandidateArchive,
    *,
    objective: str = "",
) -> dict[str, float]:
    """The prior proven scenario set: for each scenario any previously proven
    candidate (live or archived — champions *and* stepping stones) scored
    under ``objective``, the best historical score achieved.

    Best-ever is the conservative reference: a candidate that silently gives
    back the best capability any stepping stone proved is erasing historical
    capability even if it still beats today's champion.
    """
    proven: dict[str, float] = {}
    for genome in _population_plus_archive(population, archive).values():
        if objective and (genome.provenance is None or genome.provenance.objective != objective):
            continue
        for scenario, score in genome.eval_scores.items():
            if scenario not in proven or score > proven[scenario]:
                proven[scenario] = score
    return proven


def evaluate_retention(
    population: PopulationStore,
    archive: CandidateArchive,
    candidate: PipelineGenome,
    gate: RetentionGate,
) -> RetentionReport | None:
    """Run the retention evaluation for ``candidate``; ``None`` when there is
    no prior proven set to defend yet (first candidate under an objective has
    nothing historical to regress against)."""
    provenance = complete_provenance(candidate)
    proven = proven_scenario_scores(population, archive, objective=provenance.objective)
    if not proven:
        return None
    return gate.evaluate(candidate, proven)
