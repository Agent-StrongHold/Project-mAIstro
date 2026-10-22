"""Retrodiction prefilter (M4-A5): replay candidates against prior cycle
traces BEFORE spending a fresh isolated execution / frontier-model call.

The prefilter is a triage gate, not an evaluator. It answers one question —
"have we already seen this exact candidate behave, and how?" — by
content-addressing prior evaluation traces and replaying them against a
proposed candidate. It may only REJECT obvious repeats/known-total-failures
or DEPRIORITIZE low-information repeats to the back of the eval batch; it
never scores a candidate, never promotes one, and never substitutes for the
real harness: promotion still requires the live evaluator/sandbox path plus
the human approval gate (``PipelineGenome.approved_for_promotion`` via
``PopulationStore.promote_audited``).

Design notes / reconciliations:

- ADR-088 marks maistro-evolve experimental (no stability contract); this
  module is internal to the package and off-by-default-able via
  ``EvolutionConfig.retrodiction = "off"``.
- SPEC-202 signal honesty: trace evidence recorded from a STUB result
  (transient gateway/agent failure) is never recorded at all, so it can
  never drive a rejection. Only real prior behavior rejects.
- False-negative risk is measured directly: every decision is recorded, and
  whenever a candidate that was rejected (shadow mode) or deprioritized
  later succeeds in a full evaluation, the outcome is counted as a false
  negative in ``PrefilterStats``. Run in ``"shadow"`` mode first to measure
  the false-negative rate on your workload before trusting ``"enforce"``.
- Cost/runtime savings are measured from the traces a rejection skips: the
  recorded per-benchmark ``cost_usd``/``duration_seconds`` of the runs the
  candidate would otherwise have repeated.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from .fitness import hard_gate_threshold
from .types import EvalResult, PipelineGenome

#: Bumped whenever the fingerprint payload or trace semantics change in a
#: way that would make old traces incomparable to new candidates. Traces
#: carry their version; the prefilter only replays traces it understands.
TRACE_SCHEMA_VERSION = 1

Verdict = Literal["allow", "reject", "deprioritize"]
PrefilterMode = Literal["enforce", "shadow"]


def genome_fingerprint(genome: PipelineGenome) -> str:
    """Deterministic content address of a genome's BEHAVIORAL payload.

    Two genomes with the same fingerprint will submit byte-identical
    prompts/models/params to the harness, so a recorded trace for one is a
    faithful retrodiction for the other. Deliberately excluded: ``id``,
    ``name``, lineage ids, timestamps, ``eval_scores``, ``fitness_score``,
    ``harness_params`` (bookkeeping, not behavior) and ``eval_weights``
    (scoring config — affects fitness math, not what the harness runs).
    Node order is normalized (sorted by node id) so structurally identical
    topologies built in different orders fingerprint the same.
    """
    payload = {
        "schema": TRACE_SCHEMA_VERSION,
        "nodes": sorted(
            (node.model_dump() for node in genome.topology.nodes),
            key=lambda n: n["id"],
        ),
        "edges": sorted(
            (edge.model_dump() for edge in genome.topology.edges),
            key=lambda e: json.dumps(e, sort_keys=True),
        ),
        "entry_node": genome.topology.entry_node,
        "max_cycles": genome.topology.max_cycles,
        "beam_width": genome.topology.beam_width,
        "use_scout": genome.topology.use_scout,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class TraceRecord(BaseModel):
    """One recorded benchmark outcome for one genome fingerprint.

    ``trace_id`` is content-addressed (schema version + fingerprint +
    benchmark + per-ledger sequence) and is the addressable handle used in
    prefilter reasons, so any rejection can be traced back to the exact
    prior evidence that caused it.
    """

    trace_id: str
    schema_version: int
    genome_fingerprint: str
    genome_id: str
    benchmark: str
    score: float
    cost_usd: float
    duration_seconds: float
    samples_evaluated: int
    fidelity: str | None = None
    stub: bool = False
    cycle_index: int | None = None
    recorded_at: str


class TraceLedger:
    """In-memory, versioned, addressable store of prior evaluation traces.

    The ledger is the "prior cycle traces/evidence" side of the retrodiction
    contract: ``EvolutionCycle`` records every real benchmark result here as
    it folds scores, so later cycles (and the self-improve verify paths) can
    replay them deterministically. Same genome payload + same ledger state
    ⇒ same replay, every time: no clocks, no randomness in lookup.
    """

    def __init__(self, schema_version: int = TRACE_SCHEMA_VERSION) -> None:
        self.schema_version = schema_version
        self._by_fingerprint: dict[str, list[TraceRecord]] = {}
        self._by_id: dict[str, TraceRecord] = {}
        self._seq = 0

    def __len__(self) -> int:
        return len(self._by_id)

    def record(
        self,
        genome: PipelineGenome,
        results: Sequence[EvalResult],
        *,
        cycle_index: int | None = None,
        recorded_at: str | None = None,
    ) -> list[TraceRecord]:
        """Record real benchmark results for a genome.

        STUB results (``metadata["stub"]`` — SPEC-202 noise) are refused as
        evidence entirely: they must never be replayed into a rejection.
        """
        from datetime import UTC, datetime

        fingerprint = genome_fingerprint(genome)
        recorded: list[TraceRecord] = []
        for r in results:
            stub = bool(r.metadata.get("stub"))
            if stub:
                continue
            self._seq += 1
            trace = TraceRecord(
                trace_id=f"rt-v{self.schema_version}-{fingerprint[:16]}-{r.benchmark}-{self._seq}",
                schema_version=self.schema_version,
                genome_fingerprint=fingerprint,
                genome_id=genome.id,
                benchmark=r.benchmark,
                score=r.score,
                cost_usd=r.cost_usd,
                duration_seconds=r.duration_seconds,
                samples_evaluated=r.samples_evaluated,
                fidelity=r.metadata.get("fidelity"),
                stub=stub,
                cycle_index=cycle_index,
                recorded_at=recorded_at or datetime.now(UTC).isoformat(),
            )
            self._by_fingerprint.setdefault(fingerprint, []).append(trace)
            self._by_id[trace.trace_id] = trace
            recorded.append(trace)
        return recorded

    def get(self, trace_id: str) -> TraceRecord | None:
        """Addressable lookup by trace_id."""
        return self._by_id.get(trace_id)

    def traces_for(self, fingerprint: str, benchmark: str | None = None) -> list[TraceRecord]:
        traces = self._by_fingerprint.get(fingerprint, [])
        if benchmark is None:
            return list(traces)
        return [t for t in traces if t.benchmark == benchmark]

    def replay(self, genome: PipelineGenome, benchmarks: Iterable[str]) -> dict[str, TraceRecord]:
        """Deterministic retrodiction: the latest recorded trace per requested
        benchmark for this genome's fingerprint.

        "Latest" is well-defined (ledger insertion order — traces are
        appended as evaluations complete), so repeated replays over an
        unchanged ledger return identical evidence. Benchmarks with no
        recorded trace are simply absent from the result.
        """
        fingerprint = genome_fingerprint(genome)
        latest: dict[str, TraceRecord] = {}
        for trace in self.traces_for(fingerprint):
            latest[trace.benchmark] = trace
        return {b: latest[b] for b in benchmarks if b in latest}


class PrefilterReason(BaseModel):
    code: str
    detail: str
    trace_ids: list[str] = []


class PrefilterDecision(BaseModel):
    genome_id: str
    fingerprint: str
    verdict: Verdict
    mode: PrefilterMode
    schema_version: int
    reasons: list[PrefilterReason] = []
    #: Predicted (replayed) score per benchmark that had recorded evidence.
    predicted_scores: dict[str, float] = {}
    #: What a REJECT verdict skips (0 for allow/deprioritize, which still run).
    evals_saved: int = 0
    cost_saved_usd: float = 0.0
    runtime_saved_seconds: float = 0.0

    def summary(self) -> dict[str, Any]:
        return self.model_dump()


class PrefilterConfig(BaseModel):
    mode: PrefilterMode = "enforce"
    # Reject a repeat whose replayed evidence scores below the hard gate on
    # every covered benchmark (a known-total-failure duplicate).
    reject_total_failure: bool = True
    # Move expected-pass repeats to the back of the eval batch instead of
    # evaluating them first.
    deprioritize_repeat: bool = True


class PrefilterStats(BaseModel):
    """Cumulative accounting for one prefilter instance.

    False-negative accounting: ``false_negative_rate`` is measured over the
    candidates whose full-evaluation outcome was actually observed after a
    would-have-filtered verdict (deprioritized candidates in enforce mode;
    verdict-rejected candidates too in shadow mode, because shadow still
    evaluates everything). A candidate that later succeeds in full
    evaluation counts as a false negative — the filter was wrong about it.
    """

    candidates_seen: int = 0
    allowed: int = 0
    deprioritized: int = 0
    rejected: int = 0
    evals_saved: int = 0
    cost_saved_usd: float = 0.0
    runtime_saved_seconds: float = 0.0
    #: Candidates with a reject/deprioritize verdict whose full-eval outcome
    # was observed (the denominator of the false-negative rate).
    filtered_outcomes_observed: int = 0
    false_negatives: int = 0
    false_negative_events: list[dict[str, Any]] = Field(default=[], max_length=200)

    @property
    def false_negative_rate(self) -> float | None:
        if self.filtered_outcomes_observed == 0:
            return None
        return self.false_negatives / self.filtered_outcomes_observed

    def record_verdict(
        self,
        verdict: Verdict,
        *,
        evals_saved: int = 0,
        cost_saved_usd: float = 0.0,
        runtime_saved_seconds: float = 0.0,
    ) -> None:
        """Account one decided candidate; savings apply to rejects only."""
        if verdict == "allow":
            self.allowed = self.allowed + 1
            return
        if verdict == "deprioritize":
            self.deprioritized = self.deprioritized + 1
            return
        self.rejected = self.rejected + 1
        self.evals_saved = self.evals_saved + evals_saved
        self.cost_saved_usd = self.cost_saved_usd + cost_saved_usd
        self.runtime_saved_seconds = self.runtime_saved_seconds + runtime_saved_seconds

    def summary(self) -> dict[str, Any]:
        data = self.model_dump()
        data["false_negative_rate"] = self.false_negative_rate
        return data


class RetrodictionPrefilter:
    """Decides allow/reject/deprioritize for a proposed candidate by
    replaying it against prior traces, and accounts for what that saved.

    In ``"shadow"`` mode decisions are recorded exactly as in ``"enforce"``
    but callers ignore reject/deprioritize verdicts (everything is
    evaluated), which is what makes the false-negative rate measurable
    before the filter is trusted to skip work.
    """

    def __init__(self, ledger: TraceLedger, config: PrefilterConfig | None = None) -> None:
        self.ledger = ledger
        self.config = config or PrefilterConfig()
        self.stats = PrefilterStats()

    def decide(self, genome: PipelineGenome, benchmarks: Sequence[str]) -> PrefilterDecision:
        self.stats.candidates_seen += 1
        fingerprint = genome_fingerprint(genome)
        replayed = self.ledger.replay(genome, benchmarks)
        reasons: list[PrefilterReason] = []
        predicted_scores = {b: t.score for b, t in replayed.items()}

        gap_reason = self._coverage_reason(replayed, benchmarks)
        if gap_reason is not None:
            reasons.append(gap_reason)
            verdict: Verdict = "allow"
            evals_saved = 0
            cost_saved_usd = 0.0
            runtime_saved_seconds = 0.0
        else:
            # Full evidence coverage for every requested benchmark.
            trace_ids = [t.trace_id for t in replayed.values()]
            verdict, reason, evals_saved, cost_saved_usd, runtime_saved_seconds = (
                self._full_coverage_outcome(genome, replayed, benchmarks, trace_ids)
            )
            if reason is not None:
                reasons.append(reason)

        self.stats.record_verdict(
            verdict,
            evals_saved=evals_saved,
            cost_saved_usd=cost_saved_usd,
            runtime_saved_seconds=runtime_saved_seconds,
        )

        return PrefilterDecision(
            genome_id=genome.id,
            fingerprint=fingerprint,
            verdict=verdict,
            mode=self.config.mode,
            schema_version=self.ledger.schema_version,
            reasons=reasons,
            predicted_scores=predicted_scores,
            evals_saved=evals_saved,
            cost_saved_usd=cost_saved_usd,
            runtime_saved_seconds=runtime_saved_seconds,
        )

    @staticmethod
    def _coverage_reason(
        replayed: dict[str, TraceRecord], benchmarks: Sequence[str]
    ) -> PrefilterReason | None:
        """Why incomplete replay coverage forces a full evaluation, if it does."""
        if not replayed:
            return PrefilterReason(
                code="no_prior_evidence",
                detail="no recorded trace for this fingerprint; full evaluation required",
            )
        if len(replayed) < len(set(benchmarks)):
            return PrefilterReason(
                code="partial_prior_evidence",
                detail=(
                    "evidence covers "
                    f"{sorted(replayed)}/{sorted(set(benchmarks))}; "
                    "uncovered benchmarks must run, so the candidate runs"
                ),
                trace_ids=[t.trace_id for t in replayed.values()],
            )
        return None

    def _full_coverage_outcome(
        self,
        genome: PipelineGenome,
        replayed: dict[str, TraceRecord],
        benchmarks: Sequence[str],
        trace_ids: list[str],
    ) -> tuple[Verdict, PrefilterReason | None, int, float, float]:
        """Verdict, triage reason and saved spend for a fully-covered replay."""
        below_gate = {b: t.score < hard_gate_threshold(b) for b, t in replayed.items()}
        verdict: Verdict = "allow"
        reason: PrefilterReason | None = None
        if self.config.reject_total_failure and all(below_gate.values()):
            verdict = "reject"
            reason = PrefilterReason(
                code="prior_total_failure",
                detail=(
                    "replayed evidence scores below the hard gate on "
                    "every requested benchmark; skipping a known "
                    "total-failure repeat"
                ),
                trace_ids=trace_ids,
            )
        elif genome.eval_scores and all(b in genome.eval_scores for b in replayed):
            # Exact repeat of a genome this population already scored.
            if self.config.deprioritize_repeat:
                verdict = "deprioritize"
            reason = PrefilterReason(
                code="repeat_already_scored",
                detail=(
                    "candidate already carries eval_scores for the "
                    "requested benchmarks; low re-evaluation value"
                ),
                trace_ids=trace_ids,
            )
        elif self.config.deprioritize_repeat:
            # Unscored duplicate of an already-evaluated payload: the
            # copy still needs scores to survive culling, but it is a
            # low-information eval — triage it to the back of the batch.
            verdict = "deprioritize"
            reason = PrefilterReason(
                code="duplicate_of_scored_payload",
                detail=(
                    "byte-identical behavioral payload was already "
                    "evaluated; the copy is triaged behind novel work"
                ),
                trace_ids=trace_ids,
            )

        if verdict != "reject":
            return verdict, reason, 0, 0.0, 0.0
        return (verdict, reason, *self._reject_savings(benchmarks, list(replayed.values())))

    @staticmethod
    def _reject_savings(
        benchmarks: Sequence[str], traces: list[TraceRecord]
    ) -> tuple[int, float, float]:
        """Spend a rejected repeat avoids: one eval per requested benchmark."""
        return (
            len(set(benchmarks)),
            sum(t.cost_usd for t in traces),
            sum(t.duration_seconds for t in traces),
        )

    def would_filter(self, decision: PrefilterDecision) -> bool:
        """Whether this verdict filters the candidate (mode-aware).

        Shadow mode never filters — it only records — so the outcome of
        would-be-rejected candidates stays observable and the false-negative
        rate stays measurable.
        """
        return decision.mode == "enforce" and decision.verdict == "reject"

    def deprioritizes(self, decision: PrefilterDecision) -> bool:
        return decision.mode == "enforce" and decision.verdict == "deprioritize"

    def observe_outcome(
        self, decision: PrefilterDecision, passed: bool, *, genome_id: str | None = None
    ) -> bool:
        """Reconcile a full-evaluation outcome against the earlier verdict.

        Call ONLY for candidates that were actually evaluated after a
        filtering verdict (reject-in-shadow or deprioritize). Returns True
        when the outcome was a false negative: the filter wanted to skip or
        park the candidate, but full evaluation succeeded anyway.
        """
        if decision.verdict not in ("reject", "deprioritize"):
            return False
        self.stats.filtered_outcomes_observed += 1
        if not passed:
            return False
        self.stats.false_negatives += 1
        if len(self.stats.false_negative_events) < 200:
            self.stats.false_negative_events.append(
                {
                    "genome_id": genome_id or decision.genome_id,
                    "fingerprint": decision.fingerprint,
                    "verdict": decision.verdict,
                    "mode": decision.mode,
                    "reason_codes": [r.code for r in decision.reasons],
                }
            )
        return True
