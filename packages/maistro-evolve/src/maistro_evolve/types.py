from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

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


class CandidateProvenance(BaseModel):
    """Immutable lineage/identity record for one candidate genome (M4-A6).

    Every proposed improvement carries the full answer to "where did this
    candidate come from": its parent(s), the mutation/operator that produced
    it, the source objective it was optimized under, a content version of its
    evolvable prompt/template material, and the canonical evaluation Runs that
    scored it. Producers stamp it at creation (see ``archive.stamp_provenance``);
    the promotion gate refuses a candidate whose record is incomplete.
    """

    parents: list[str] = Field(default_factory=list)
    operator: str = ""
    objective: str = ""
    prompt_version: str = ""
    evaluation_run_ids: list[str] = Field(default_factory=list)
    # Free-form operator context (e.g. "crossover+mutate_all") that refines
    # ``operator`` without multiplying enum values.
    detail: str = ""


class PipelineGenome(BaseModel):
    id: str
    name: str
    topology: DAGTopology
    eval_weights: EvalWeights
    harness_params: dict[str, Any] = {}
    fitness_score: float | None = None
    eval_scores: dict[str, float] = {}
    generation: int = 0
    parent_a_id: str | None = None
    parent_b_id: str | None = None
    created_at: str
    updated_at: str
    # M4-A6 candidate lineage record. Optional so genomes/tests predating it
    # stay valid (pydantic default None); ``archive.complete_provenance`` is
    # the fail-closed completeness check the promotion gate enforces.
    provenance: CandidateProvenance | None = None
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
    weighted_eval_score: float
    cost_efficiency: float
    latency_efficiency: float
    diversity_bonus: float
    total: float
    passed_hard_gate: bool
    gate_failures: list[str] = []
