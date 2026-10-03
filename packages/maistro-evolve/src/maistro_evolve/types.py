from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .fixer_genome import FixerGenome


class DAGEdgeGenome(BaseModel):
    id: str
    from_node: str
    to_node: str | None
    condition: str | None


class NodeGenome(BaseModel):
    id: str
    role: str
    strategy: str
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    max_tool_rounds: int
    # The evolvable RSI-fixer strategy layer (ADR-070126-6386 v2) — optional so
    # existing genomes/tests that build a NodeGenome without one stay valid; only
    # meaningful for nodes used as an RSI fixer's entry (see
    # maistro_rsi.evolve_bridge.genome_to_competitor).
    fixer: FixerGenome | None = None


class DAGTopology(BaseModel):
    nodes: list[NodeGenome]
    edges: list[DAGEdgeGenome]
    entry_node: str
    max_cycles: int
    beam_width: int
    use_scout: bool


class EvalWeights(BaseModel):
    """Relative weight of each benchmark in the weighted eval score.

    **Inert legacy field (#853).** This model used to be the genome's own
    scoring policy: it rode on ``PipelineGenome.eval_weights`` through every
    mutation operator and through crossover, so a genome could materially
    change the ``_weighted_eval_score`` it was measured with without improving
    on a single benchmark. Scoring now reads the population-owned, versioned
    ``objective.EvaluationObjective`` exclusively; this field is kept only so
    persisted genomes from before #853 still load. It MUST NOT be consulted by
    fitness, selection, or promotion code, and it is no longer mutated by any
    operator.

    `osworld` was removed: `run_osworld` raises `NotImplementedError` and is not
    registered, so its 0.05 could never be applied to a real score. Weights are
    renormalised over the benchmarks that actually ran
    (`fitness._weighted_eval_score`), so removing an unusable entry changes no
    computed value — it just stops the model from advertising a benchmark this
    repo cannot run. Persisted genomes carrying an `osworld` key still load;
    pydantic ignores the extra field.
    """

    # Field names double as the benchmark identifiers looked up by-name from
    # `EvalResult.benchmark` / `genome.eval_scores` keys (see fitness.py's
    # `getattr(weights, bench, None)`) — must stay in lockstep with the
    # `proxy_`-prefixed identifiers in `benchmarks/__init__.py` (SPEC-202).
    proxy_ifeval: float = 0.15
    proxy_bfcl: float = 0.15
    proxy_swebench: float = 0.20
    proxy_terminalbench: float = 0.10
    proxy_tau_bench: float = 0.15
    proxy_gaia: float = 0.10
    proxy_ragas: float = 0.10

    # The real tier registers under bare identifiers (`REAL_BENCHMARKS`), so a
    # real run's `EvalResult.benchmark` is `ifeval`/`bfcl`. Without these the
    # lookup misses and falls back to `_DEFAULT_BENCH_WEIGHT`, silently weighting
    # the official-harness scores differently from their proxy counterparts.
    ifeval: float = 0.15
    bfcl: float = 0.15


class PipelineGenome(BaseModel):
    id: str
    name: str
    topology: DAGTopology
    # Inert legacy scoring policy (see EvalWeights above): kept for persisted-
    # genome compatibility, ignored by every scorer since #853. Never mutated.
    eval_weights: EvalWeights
    harness_params: dict[str, Any] = {}
    fitness_score: float | None = None
    eval_scores: dict[str, float] = {}
    # Per-benchmark verification provenance (#384): for each entry in
    # ``eval_scores``, the verified method the score came from (the
    # ``method`` of the runner's ``metadata["evidence"]`` — e.g.
    # "structured-call-match", "llm-judge", "exact-match+llm-judge"), or
    # "unverified" when a result carried no evidence record. Champion
    # selection must be able to name the evidence behind every score; this
    # is that record, folded alongside the score it describes.
    eval_evidence: dict[str, str] = {}
    generation: int = 0
    parent_a_id: str | None = None
    parent_b_id: str | None = None
    created_at: str
    updated_at: str
    # RSI safety: promotion to live traffic requires an explicit human
    # approval gate (set externally, e.g. via human.approve_draft) — winning
    # tournament/fitness evaluation alone never sets this. Defaults closed.
    approved_for_promotion: bool = False
    # Set by the audited promotion path (PopulationStore.promote_audited —
    # the raw transition is private, #342); tracks which genome is currently
    # serving live traffic, and what to roll back to if it regresses.
    is_active: bool = False
    rollback_target_id: str | None = None


class EvalResult(BaseModel):
    benchmark: str
    score: float
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    samples_evaluated: int = 0
    metadata: dict[str, Any] = {}


class FitnessComponents(BaseModel):
    """One fitness computation, fully attributable (#853).

    Components carry their semantic role (``component_roles``), the objective
    version that produced them, and a digest of the exact input evidence — so
    the same evidence deterministically recomputes the same score, and any
    movement across cycles is traceable to a recorded evidence or objective
    change.

    Missing measurements are ``None``, never an ideal value: cost/latency/Elo
    that were never recorded score the objective's pessimistic
    ``missing_evidence_credit`` in ``total`` and are named in
    ``missing_evidence`` (#853 — absence is no longer a perfect 1.0).
    """

    weighted_eval_score: float
    # Measured task quality AFTER the hard gates (0.0 when gated out).
    # Elo/diversity/context terms never enter this field — promotion and
    # correctness reasoning must read this, not ``total``.
    capability_score: float
    cost_efficiency: float | None
    latency_efficiency: float | None
    diversity_bonus: float
    elo_bonus: float | None
    total: float
    passed_hard_gate: bool
    gate_failures: list[str] = []
    # Which components had no measurement (scored pessimistically).
    missing_evidence: list[str] = []
    # Version of the EvaluationObjective this score was computed under.
    objective_version: str = ""
    # sha256 over the exact inputs (evidence + objective) — same evidence
    # recomputes the same hash and the same total.
    evidence_hash: str = ""
    # component name -> semantic role (see fitness.COMPONENT_ROLES).
    component_roles: dict[str, str] = {}
