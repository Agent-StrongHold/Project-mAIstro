"""Producer attribution for the evolve search (M4-A8, issue #115).

The search loop already knows *which genome* a candidate descends from
(``parent_a_id``/``parent_b_id``), but not *which producer* — generator,
mutation operator, prompt operator, or search operator — manufactured it, nor
how well that producer's products actually score. Without that, the search can
only retain winning candidates; it cannot improve the improvement process
itself (the DGM/HyperAgents "self-improvement of the improver" lever, and the
CoinSwarm prompt/generator feedback loop).

This module closes that loop with three small pieces:

- **CandidateOrigin** — frozen provenance stamped onto every candidate at
  birth: the producing operator's identity *and version*, its parents, the
  parents' stored scores at production time (the baseline any later delta is
  measured against), the producing pipeline chain, and the evaluation context
  the candidate was produced under.
- **ProducerLedger** — an append-only credit ledger. Evaluation results are
  credited to the producing operator as immutable ``CreditEvent``s (strictly
  sequenced, never rewritten or decayed), folded into per-(producer,
  eval-context) statistics. Positive *and* negative credit accumulate;
  repeated regressions/failures stay visible and demote an operator's weight
  without ever erasing its history.
- **Operator favoring** — ``operator_weights``/``select_operator`` turn those
  statistics into selection weights for the mutation operators, with a hard
  exploration floor so favoring productive operators can never collapse
  diversity to a single operator (mirroring the diversity guarantees the
  island model and fitness diversity bonus already provide upstream).

Scoping: credit statistics are bucketed by the *evaluation* context (harness
fidelity + benchmark set + optional scope id). A score earned under a proxy
harness never blends into real-harness statistics — the same discipline as
SPEC-202's fidelity tiers and the harness's own "do not compare a
real-harness fitness number to a proxy-harness one" rule.

Persistence posture: the ledger is deliberately process-local, exactly like
``EloTournament`` (see ``cycle.EvolutionCycle``) — the population store
persists genomes (which carry their own frozen origin), while tournament and
credit state describe one evolving session. Candidate history itself is never
rewritten: origins are frozen models, and the ledger refuses to re-register a
candidate id with a different origin.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover - import cycle guard (types imports this module)
    from .types import PipelineGenome

#: Version of the attribution schema itself — bump when CreditEvent/CandidateOrigin
#: change shape, so downstream auditors can tell which records they are reading.
ATTRIBUTION_SCHEMA_VERSION = "1"

#: Per-producer semantic versions. A producer that changes behavior bumps its
#: version here, which starts a fresh credit identity (old statistics remain
#: attributable to the old version — producer history is never blended across
#: behavior changes).
PRODUCER_VERSIONS: dict[str, str] = {
    "seed": "1",
    "crossover": "1",
    "mutate_topology": "1",
    "mutate_node": "1",
    "mutate_prompt": "1",
    "mutate_fixer_genome": "1",
    "mutate_all": "1",
    "mutate_selected": "1",
    "crossover_and_mutate": "1",
    "reflective_improve": "1",
    "hyper_mutator": "1",
    "optimize_topology": "1",
}


class ProducerKind(StrEnum):
    """What kind of search-process component produced a candidate."""

    GENERATOR = "generator"  # creates candidates (seed, crossover)
    MUTATION_OPERATOR = "mutation_operator"  # typed genome mutation operators
    PROMPT_OPERATOR = "prompt_operator"  # free-text prompt evolution (reflect)
    SEARCH_OPERATOR = "search_operator"  # guided meta-search (hyper-mutator)
    SOURCE = "source"  # external source (scout objective, human, import)


class ProducerIdentity(BaseModel):
    """Who produced a candidate — kind, registered name, and version."""

    model_config = ConfigDict(frozen=True)

    kind: ProducerKind
    name: str
    version: str = "1"

    def key(self) -> str:
        """Canonical, comparable identity key (``kind:name@version``)."""
        return f"{self.kind.value}:{self.name}@{self.version}"


def producer_identity(name: str, kind: ProducerKind) -> ProducerIdentity:
    """Build a ProducerIdentity from the version registry.

    Fails closed: an unregistered producer name is a programming error (a new
    operator must declare its version to be attributable), not a silent
    ``version="0"``.
    """
    try:
        version = PRODUCER_VERSIONS[name]
    except KeyError:
        raise KeyError(
            f"producer {name!r} is not registered in attribution.PRODUCER_VERSIONS; "
            "add it there (with a version) so candidates it produces are attributable"
        ) from None
    return ProducerIdentity(kind=kind, name=name, version=version)


class EvalContext(BaseModel):
    """The comparable evaluation scope credit is aggregated within.

    Two evaluations are comparable when they ran at the same harness fidelity,
    against the same benchmark set, in the same optional scope (e.g. one
    evolving session / island run). Statistics from different contexts are
    kept apart so a proxy-harness fluke can never float a real-harness
    operator ranking.
    """

    model_config = ConfigDict(frozen=True)

    fidelity: str = "unknown"
    benchmarks: tuple[str, ...] = ()
    scope: str = ""

    @classmethod
    def from_harness(cls, harness: Any, benchmarks: Sequence[str], scope: str = "") -> EvalContext:
        fidelity = getattr(harness, "fidelity", "unknown")
        return cls(fidelity=str(fidelity), benchmarks=tuple(sorted(benchmarks)), scope=scope)

    def key(self) -> str:
        # Sorted so the key is canonical regardless of construction order —
        # two contexts covering the same benchmark set are the same scope.
        return f"{self.fidelity}|{','.join(sorted(self.benchmarks))}|{self.scope}"


class CandidateOrigin(BaseModel):
    """Immutable provenance record stamped onto a candidate at birth.

    ``baseline_scores`` snapshots the parents' stored benchmark scores at
    production time — that snapshot, not the parents' *current* scores, is
    what a later credit delta is measured against, so a candidate's credit is
    stable even as its ancestors keep evolving.
    """

    model_config = ConfigDict(frozen=True)

    producer: ProducerIdentity
    parents: tuple[str, ...] = ()
    #: Population-visible ancestors behind any transient intermediate objects
    #: (e.g. the crossover child a `crossover_and_mutate` mutation chain consumed).
    upstream: tuple[str, ...] = ()
    #: Producer keys of every pipeline stage that shaped this candidate, in order.
    chain: tuple[str, ...] = ()
    baseline_scores: dict[str, float] = {}
    context: EvalContext = Field(default_factory=EvalContext)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    note: str = ""


CreditOutcome = Literal["improvement", "regression", "neutral", "failure"]


class CreditEvent(BaseModel):
    """One append-only credit record: an evaluation result attributed to a producer."""

    sequence: int
    candidate_id: str  # "" for rejected-proposal events (the proposal was never kept)
    producer: ProducerIdentity
    context_key: str
    benchmark: str
    score: float
    baseline: float | None = None
    delta: float | None = None
    outcome: CreditOutcome
    accepted: bool = False
    #: True when the evaluation itself was a stub (transient failure — SPEC-202
    #: noise). Stub events count as *failures*, never as signal.
    stub: bool = False
    ts: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ProducerStats(BaseModel):
    """Accumulated credit for one producer within one evaluation context.

    ``attempts`` counts *signal* events (improvements + regressions + neutral);
    stub failures are counted separately in ``failures`` so transient
    infrastructure noise neither inflates nor dilutes success rates.
    Counters are monotonic — there is no decay and no reset, so negative
    credit is retained for the producer's lifetime (M4-A8: "negative credit is
    retained for repeated regressions/failures").
    """

    producer_key: str
    context_key: str
    attempts: int = 0
    improvements: int = 0
    regressions: int = 0
    failures: int = 0
    neutral: int = 0
    total_delta: float = 0.0
    last_delta: float | None = None

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.improvements / self.attempts

    @property
    def regression_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.regressions / self.attempts

    @property
    def avg_delta(self) -> float:
        if self.attempts == 0:
            return 0.0
        return self.total_delta / self.attempts


class ProducerLedger:
    """Append-only producer credit ledger and operator-weight authority.

    Process-local by design (same posture as ``EloTournament``): it describes
    one evolving session against one population store. The audit log
    (``events``) is strictly sequenced and append-only — credit is recorded,
    never rewritten — while per-(producer, context) statistics are the
    aggregate view of that log.
    """

    def __init__(
        self,
        *,
        repeated_regression_limit: int = 3,
        exploration_floor: float = 0.2,
    ) -> None:
        if repeated_regression_limit < 1:
            raise ValueError("repeated_regression_limit must be >= 1")
        if not 0.0 <= exploration_floor <= 1.0:
            raise ValueError("exploration_floor must be within [0, 1]")
        self._repeated_regression_limit = repeated_regression_limit
        self._exploration_floor = exploration_floor
        self._events: list[CreditEvent] = []
        self._origins: dict[str, CandidateOrigin] = {}
        self._stats: dict[tuple[str, str], ProducerStats] = {}

    # ------------------------------------------------------------------ audit

    @property
    def events(self) -> tuple[CreditEvent, ...]:
        """The append-only credit log, in strict sequence order."""
        return tuple(self._events)

    @property
    def exploration_floor(self) -> float:
        return self._exploration_floor

    @property
    def repeated_regression_limit(self) -> int:
        return self._repeated_regression_limit

    # ------------------------------------------------------------- candidates

    def origin_of(self, candidate_id: str) -> CandidateOrigin | None:
        return self._origins.get(candidate_id)

    def register_candidate(self, genome: PipelineGenome) -> CandidateOrigin:
        """Register a candidate's origin exactly once.

        Raises if the candidate has no origin (an unattributable candidate
        must not silently enter credited evaluation) or if a *different*
        origin is presented for an already-registered id — candidate history
        is never rewritten.
        """
        origin = genome.origin
        if origin is None:
            raise ValueError(
                f"candidate {genome.id!r} has no CandidateOrigin; producers must "
                "stamp origins at birth so credit is attributable"
            )
        existing = self._origins.get(genome.id)
        if existing is not None:
            if existing != origin:
                raise ValueError(
                    f"candidate {genome.id!r} origin rewrite attempted — candidate "
                    "history is append-only and cannot be rewritten"
                )
            return existing
        self._origins[genome.id] = origin
        return origin

    # ----------------------------------------------------------------- credit

    def credit(
        self,
        genome: PipelineGenome,
        benchmark: str,
        score: float,
        *,
        context: EvalContext,
        accepted: bool = False,
        stub: bool = False,
    ) -> CreditEvent | None:
        """Credit one evaluated benchmark result to the candidate's producer.

        ``context`` is the *evaluation* context (the scope the score was
        earned in), which may legitimately differ from the production context
        frozen in the origin. Returns None (and records nothing) for
        candidates without an origin — unattributable candidates (e.g. seed
        genomes) are simply outside the credit system, not errors.
        """
        origin = self._origins.get(genome.id)
        if origin is None:
            if genome.origin is not None:
                origin = self.register_candidate(genome)
            else:
                return None
        baseline = origin.baseline_scores.get(benchmark)
        delta = None if baseline is None else round(score - baseline, 4)
        outcome: CreditOutcome
        if stub:
            outcome = "failure"
        elif delta is None:
            outcome = "neutral"
        elif delta > 0:
            outcome = "improvement"
        elif delta < 0:
            outcome = "regression"
        else:
            outcome = "neutral"
        return self._record(
            CreditEvent(
                sequence=len(self._events) + 1,
                candidate_id=genome.id,
                producer=origin.producer,
                context_key=context.key(),
                benchmark=benchmark,
                score=score,
                baseline=baseline,
                delta=delta,
                outcome=outcome,
                accepted=accepted,
                stub=stub,
            )
        )

    def credit_rejected_proposal(
        self,
        producer: ProducerIdentity,
        context: EvalContext,
        benchmark: str,
        baseline: float,
        score: float,
    ) -> CreditEvent:
        """Credit a *verified but rejected* proposal (propose-then-verify loops
        in ``reflect``/``hyper_mutator``): the candidate never entered the
        population, but the producer's negative/neutral credit is still
        retained — repeated failed proposals demote the operator just like
        persisted regressions do."""
        delta = round(score - baseline, 4)
        outcome: CreditOutcome = (
            "improvement" if delta > 0 else ("regression" if delta < 0 else "neutral")
        )
        return self._record(
            CreditEvent(
                sequence=len(self._events) + 1,
                candidate_id="",
                producer=producer,
                context_key=context.key(),
                benchmark=benchmark,
                score=score,
                baseline=baseline,
                delta=delta,
                outcome=outcome,
                accepted=False,
                stub=False,
            )
        )

    def _record(self, event: CreditEvent) -> CreditEvent:
        self._events.append(event)
        key = (event.producer.key(), event.context_key)
        stats = self._stats.get(key)
        if stats is None:
            stats = ProducerStats(producer_key=key[0], context_key=key[1])
            self._stats[key] = stats
        if event.outcome == "failure":
            stats.failures += 1  # stub noise: counted, but not as an attempt
        else:
            stats.attempts += 1
            if event.outcome == "improvement":
                stats.improvements += 1
            elif event.outcome == "regression":
                stats.regressions += 1
            else:
                stats.neutral += 1
        if event.delta is not None:
            stats.total_delta = round(stats.total_delta + event.delta, 6)
            stats.last_delta = event.delta
        return event

    # ------------------------------------------------------------- statistics

    def stats(self, producer: ProducerIdentity, context_key: str) -> ProducerStats | None:
        return self._stats.get((producer.key(), context_key))

    def all_stats(self) -> tuple[ProducerStats, ...]:
        return tuple(self._stats.values())

    def is_repeated_regressor(self, producer: ProducerIdentity, context_key: str) -> bool:
        """True when a producer keeps producing verified losses: at least
        ``repeated_regression_limit`` regressions AND regression-majority
        signal. The flag never expires — negative credit is retained."""
        stats = self.stats(producer, context_key)
        if stats is None:
            return False
        return stats.regressions >= self._repeated_regression_limit and stats.regression_rate >= 0.5

    def attribution_report(self, context_key: str | None = None) -> list[dict[str, Any]]:
        """Auditable dump of the credit log (optionally scoped to one context)."""
        events = (
            self._events
            if context_key is None
            else [e for e in self._events if e.context_key == context_key]
        )
        return [e.model_dump() for e in events]

    # ---------------------------------------------------- operator favoring

    def operator_weights(
        self,
        names: Sequence[str],
        context_key: str,
        *,
        kind: ProducerKind,
        exploration_floor: float | None = None,
        repeated_regression_limit: int | None = None,
    ) -> dict[str, float]:
        """Selection weights over producers, favoring productive ones while
        preserving diversity.

        Weight = Laplace-smoothed success rate + capped average-delta bonus,
        demoted (x0.25, never to zero) for repeated regressors. The whole
        distribution is then floored: collectively the operators keep at
        least ``exploration_floor`` of the probability mass spread uniformly,
        so even a perfectly-credited operator cannot starve exploration of
        the others (diversity preservation).
        """
        floor = self._exploration_floor if exploration_floor is None else exploration_floor
        limit = (
            self._repeated_regression_limit
            if repeated_regression_limit is None
            else repeated_regression_limit
        )
        if not names:
            return {}
        raw: dict[str, float] = {}
        for name in names:
            identity = producer_identity(name, kind)
            stats = self.stats(identity, context_key)
            if stats is None or stats.attempts == 0:
                base = 1.0  # untried: neutral prior, keeps newcomers competitive
            else:
                base = (stats.improvements + 1.0) / (stats.attempts + 2.0)
                base += min(max(stats.avg_delta, 0.0), 1.0) * 0.5
                if self._is_repeated_regressor(stats, limit):
                    base *= 0.25
            raw[name] = max(base, 1e-6)
        total = sum(raw.values())
        per_name_floor = floor / len(names)
        weights: dict[str, float] = {}
        for name, value in raw.items():
            share = (1.0 - floor) * (value / total)
            weights[name] = per_name_floor + share
        return weights

    def _is_repeated_regressor(self, stats: ProducerStats, limit: int) -> bool:
        return stats.regressions >= limit and stats.regression_rate >= 0.5

    def select_operator(
        self,
        names: Sequence[str],
        context_key: str,
        *,
        kind: ProducerKind,
        rng: Any = None,
        exploration_floor: float | None = None,
        repeated_regression_limit: int | None = None,
    ) -> str:
        """Weighted-random pick of one operator name (diversity-preserving).

        ``rng`` is anything with ``.choices`` — a ``random.Random`` instance or
        the ``random`` module itself (the cycle passes the module so callers'
        global seeding stays authoritative).
        """
        if not names:
            raise ValueError("select_operator requires at least one operator name")
        weights = self.operator_weights(
            names,
            context_key,
            kind=kind,
            exploration_floor=exploration_floor,
            repeated_regression_limit=repeated_regression_limit,
        )
        chooser = rng or random.Random()
        return chooser.choices(list(names), weights=[weights[n] for n in names])[0]


def stamp_origin(genome: PipelineGenome, origin: CandidateOrigin) -> PipelineGenome:
    """Return ``genome`` with ``origin`` stamped, refusing silent rewrites.

    Stamp-once discipline at the helper level: restamping with an equal origin
    is idempotent; restamping with a different one raises. (The producing
    call-chains in ``mutate``/``crossover`` build the complete origin before
    stamping, so a constructed candidate carries exactly one final origin.)
    """
    current = genome.origin
    if current is not None:
        if current != origin:
            raise ValueError(
                f"candidate {genome.id!r} already carries a different origin — "
                "candidate history is never rewritten"
            )
        return genome
    return genome.model_copy(update={"origin": origin})
