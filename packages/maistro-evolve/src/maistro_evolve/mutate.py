from __future__ import annotations

import random
import uuid
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime

from .attribution import (
    CandidateOrigin,
    EvalContext,
    ProducerKind,
    producer_identity,
    stamp_origin,
)
from .fixer_genome import (
    FixerGenome,
    FixerStrategy,
    ReasoningEffort,
    ReviewPass,
    RiskLevel,
    TestStyle,
)
from .types import (
    DAGEdgeGenome,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)

# Default model pool for mutation/seeding when the caller doesn't constrain one.
# IMPORTANT: pass ``models=[...]`` (the run's actual routable roster, e.g.
# EvolutionConfig.allowed_models) wherever possible — mutating a genome onto a
# model the gateway can't serve is a guaranteed-0 evaluation, and the dead gene
# then SPREADS through breeding/hyper-mutation (observed live: a mutated
# `gemini-2.5-flash` child burned evals on 429s across two generations).
MODEL_REGISTRY = [
    "cerebras-qwen-3-235b-a22b-2507",
    "gpt-4o",
    "claude-sonnet-4-20250514",
    "gemini-2.5-pro",
    "mistral-large",
    "gemini-2.5-flash",
]

STRATEGY_LIST = ["react", "plan_execute", "direct", "delegate"]

PROMPT_VARIATIONS = [
    "Think step by step before answering.",
    "Be concise and direct.",
    "Verify your reasoning before concluding.",
    "Consider edge cases.",
    "Prioritize accuracy over speed.",
]


def _fresh_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# The mutation-operator registry (M4-A8): the closed set of typed mutation
# operators the ledger can credit and favor. Order is the application order
# used by ``mutate_all``.
MUTATION_OPERATOR_NAMES: tuple[str, ...] = (
    "mutate_topology",
    "mutate_node",
    "mutate_prompt",
    "mutate_fixer_genome",
    "mutate_eval_weights",
)

_MUTATION_SHORT_NAMES: dict[str, str] = {
    "mutate_topology": "topo",
    "mutate_node": "node",
    "mutate_prompt": "prompt",
    "mutate_fixer_genome": "fixer",
    "mutate_eval_weights": "weight",
}


def _mutation_origin(
    producer_name: str,
    parent: PipelineGenome,
    origin_context: EvalContext | None,
    *,
    note: str = "",
) -> CandidateOrigin:
    """Build the CandidateOrigin a mutation operator stamps onto its child:
    the operator's registered identity+version, the parent link, the parent's
    stored scores as the credit baseline, and the (optional) eval context."""
    producer = producer_identity(producer_name, ProducerKind.MUTATION_OPERATOR)
    return CandidateOrigin(
        producer=producer,
        parents=(parent.id,),
        chain=(producer.key(),),
        baseline_scores=dict(parent.eval_scores),
        context=origin_context or EvalContext(),
        note=note,
    )


def _apply_mutation_operator(
    name: str,
    genome: PipelineGenome,
    rate: float,
    models: list[str] | None,
    *,
    stamp: bool,
    origin_context: EvalContext | None = None,
) -> PipelineGenome:
    """Uniform dispatch over the registry for composite chains."""
    if name == "mutate_topology":
        return mutate_topology(genome, rate, models, origin_context=origin_context, _stamp=stamp)
    if name == "mutate_node":
        return mutate_node(genome, rate, models, origin_context=origin_context, _stamp=stamp)
    if name == "mutate_prompt":
        return mutate_prompt(genome, rate, origin_context=origin_context, _stamp=stamp)
    if name == "mutate_fixer_genome":
        return mutate_fixer_genome(genome, rate, origin_context=origin_context, _stamp=stamp)
    if name == "mutate_eval_weights":
        return mutate_eval_weights(genome, rate, origin_context=origin_context, _stamp=stamp)
    raise ValueError(f"unknown mutation operator {name!r}; known: {list(MUTATION_OPERATOR_NAMES)}")


def mutate_topology(
    genome: PipelineGenome,
    rate: float,
    models: list[str] | None = None,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    pool = models or MODEL_REGISTRY
    topo = deepcopy(genome.topology)
    if random.random() < rate and len(topo.nodes) > 1:
        removable = [n for n in topo.nodes if n.id != topo.entry_node]
        if removable:
            victim = random.choice(removable)
            topo.nodes = [n for n in topo.nodes if n.id != victim.id]
            topo.edges = [
                e for e in topo.edges if e.from_node != victim.id and e.to_node != victim.id
            ]

    if random.random() < rate:
        new_node = NodeGenome(
            id=_new_id(),
            role=random.choice(["worker", "scout", "drone"]),
            strategy=random.choice(STRATEGY_LIST),
            model=random.choice(pool),
            temperature=round(random.uniform(0.0, 1.0), 2),
            max_tokens=random.choice([256, 512, 1024, 2048, 4096, 8192, 16384]),
            system_prompt="You are a helpful assistant.",
            max_tool_rounds=random.randint(1, 20),
        )
        topo.nodes.append(new_node)
        source = random.choice([n.id for n in topo.nodes])
        topo.edges.append(
            DAGEdgeGenome(
                id=_new_id(),
                from_node=source,
                to_node=new_node.id,
                condition=None,
            )
        )

    if random.random() < rate and topo.edges:
        idx = random.randint(0, len(topo.edges) - 1)
        topo.edges.pop(idx)

    if random.random() < rate and topo.nodes:
        a = random.choice(topo.nodes)
        b_candidates = [n for n in topo.nodes if n.id != a.id]
        if b_candidates:
            b = random.choice(b_candidates)
            topo.edges.append(
                DAGEdgeGenome(
                    id=_new_id(),
                    from_node=a.id,
                    to_node=b.id,
                    condition=random.choice([None, "success", "failure", "timeout"]),
                )
            )

    child = PipelineGenome(
        id=_new_id(),
        name=genome.name + "-topo-mut",
        topology=topo,
        eval_weights=deepcopy(genome.eval_weights),
        harness_params=deepcopy(genome.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=genome.generation,
        parent_a_id=genome.id,
        parent_b_id=None,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )
    if not _stamp:
        return child
    return stamp_origin(child, _mutation_origin("mutate_topology", genome, origin_context))


def mutate_node(
    genome: PipelineGenome,
    rate: float,
    models: list[str] | None = None,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    pool = models or MODEL_REGISTRY
    topo = deepcopy(genome.topology)
    for node in topo.nodes:
        if random.random() < rate:
            node.model = random.choice(pool)
        if random.random() < rate:
            node.temperature = round(
                max(0.0, min(1.0, node.temperature + random.gauss(0, 0.15))), 2
            )
        if random.random() < rate:
            node.max_tokens = random.choice([256, 512, 1024, 2048, 4096, 8192, 16384])
        if random.random() < rate:
            node.strategy = random.choice(STRATEGY_LIST)
        if random.random() < rate:
            node.max_tool_rounds = random.randint(1, 20)
    child = PipelineGenome(
        id=_new_id(),
        name=genome.name + "-node-mut",
        topology=topo,
        eval_weights=deepcopy(genome.eval_weights),
        harness_params=deepcopy(genome.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=genome.generation,
        parent_a_id=genome.id,
        parent_b_id=None,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )
    if not _stamp:
        return child
    return stamp_origin(child, _mutation_origin("mutate_node", genome, origin_context))


def mutate_prompt(
    genome: PipelineGenome,
    rate: float,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    topo = deepcopy(genome.topology)
    for node in topo.nodes:
        if random.random() < rate:
            variation = random.choice(PROMPT_VARIATIONS)
            node.system_prompt = node.system_prompt.rstrip() + " " + variation
        if random.random() < rate:
            sentences = node.system_prompt.split(". ")
            if len(sentences) > 2:
                sentences.pop(random.randint(0, len(sentences) - 1))
                node.system_prompt = ". ".join(sentences)
    child = PipelineGenome(
        id=_new_id(),
        name=genome.name + "-prompt-mut",
        topology=topo,
        eval_weights=deepcopy(genome.eval_weights),
        harness_params=deepcopy(genome.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=genome.generation,
        parent_a_id=genome.id,
        parent_b_id=None,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )
    if not _stamp:
        return child
    return stamp_origin(child, _mutation_origin("mutate_prompt", genome, origin_context))


def mutate_eval_weights(
    genome: PipelineGenome,
    rate: float,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    if random.random() > rate:
        child = PipelineGenome(
            id=_new_id(),
            name=genome.name + "-weight-mut",
            topology=deepcopy(genome.topology),
            eval_weights=deepcopy(genome.eval_weights),
            harness_params=deepcopy(genome.harness_params),
            fitness_score=None,
            eval_scores={},
            generation=genome.generation,
            parent_a_id=genome.id,
            parent_b_id=None,
            created_at=_fresh_timestamp(),
            updated_at=_fresh_timestamp(),
        )
        if not _stamp:
            return child
        return stamp_origin(child, _mutation_origin("mutate_eval_weights", genome, origin_context))
    fields = EvalWeights.model_fields
    new_vals: dict[str, float] = {}
    for name in fields:
        current = getattr(genome.eval_weights, name)
        new_vals[name] = max(0.01, current + random.gauss(0, 0.03))
    total = sum(new_vals.values())
    for name in new_vals:
        new_vals[name] = round(new_vals[name] / total, 4)
    renorm_total = sum(new_vals.values())
    if renorm_total != 1.0:
        first_key = next(iter(new_vals))
        new_vals[first_key] = round(new_vals[first_key] + (1.0 - renorm_total), 4)
    child = PipelineGenome(
        id=_new_id(),
        name=genome.name + "-weight-mut",
        topology=deepcopy(genome.topology),
        eval_weights=EvalWeights(**new_vals),
        harness_params=deepcopy(genome.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=genome.generation,
        parent_a_id=genome.id,
        parent_b_id=None,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )
    if not _stamp:
        return child
    return stamp_origin(child, _mutation_origin("mutate_eval_weights", genome, origin_context))


def _mutate_one_fixer(fixer: FixerGenome, rate: float) -> FixerGenome:
    """Typed operators over one FixerGenome's slots: enum flip, float jitter, text
    variation. The baseline (random) mutation path; the hyper-mutator (W6) is the
    guided alternative that writes evidence-based values instead of random ones."""
    f = fixer.model_copy(deep=True)
    if random.random() < rate:
        f.strategy = random.choice(list(FixerStrategy))
    if random.random() < rate:
        f.test_style = random.choice(list(TestStyle))
    if random.random() < rate:
        f.review_pass = random.choice(list(ReviewPass))
    if random.random() < rate:
        f.risk = random.choice(list(RiskLevel))
    if random.random() < rate:
        f.reasoning_effort = random.choice([None, *list(ReasoningEffort)])
    for slot in ("minimalism", "ambition", "edge_focus", "tdd_rigor"):
        if random.random() < rate:
            setattr(f, slot, round(max(0.0, min(1.0, getattr(f, slot) + random.gauss(0, 0.15))), 2))
    if random.random() < rate and f.temperature is not None:
        f.temperature = round(max(0.0, min(2.0, f.temperature + random.gauss(0, 0.15))), 2)
    if random.random() < rate:
        f.strategy_hint = random.choice(PROMPT_VARIATIONS)
    return f


def mutate_fixer_genome(
    genome: PipelineGenome,
    rate: float,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    """Apply `_mutate_one_fixer` to every node that carries a FixerGenome. Nodes
    without one (genomes predating ADR-070126-6386 v2, or non-fixer roles) are
    left untouched — this operator only mutates the RSI-fixer strategy layer."""
    topo = deepcopy(genome.topology)
    for node in topo.nodes:
        if node.fixer is not None:
            node.fixer = _mutate_one_fixer(node.fixer, rate)
    child = PipelineGenome(
        id=_new_id(),
        name=genome.name + "-fixer-mut",
        topology=topo,
        eval_weights=deepcopy(genome.eval_weights),
        harness_params=deepcopy(genome.harness_params),
        fitness_score=None,
        eval_scores={},
        generation=genome.generation,
        parent_a_id=genome.id,
        parent_b_id=None,
        created_at=_fresh_timestamp(),
        updated_at=_fresh_timestamp(),
    )
    if not _stamp:
        return child
    return stamp_origin(child, _mutation_origin("mutate_fixer_genome", genome, origin_context))


def mutate_selected(
    genome: PipelineGenome,
    rate: float,
    models: list[str] | None = None,
    *,
    operators: Sequence[str],
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    """Apply exactly the selected mutation operators, in the given order, and
    stamp the child with a composite ``mutate_selected`` origin naming the
    applied subset — this is the entry point ledger-driven operator favoring
    uses (the cycle selects a productive, diversity-floored subset instead of
    always applying every operator).
    """
    unknown = [name for name in operators if name not in MUTATION_OPERATOR_NAMES]
    if unknown:
        raise ValueError(
            f"unknown mutation operator(s) {unknown}; known: {list(MUTATION_OPERATOR_NAMES)}"
        )
    if not operators:
        raise ValueError("mutate_selected requires at least one operator")
    current = genome
    for name in operators:
        current = _apply_mutation_operator(
            name, current, rate, models, stamp=False, origin_context=origin_context
        )
    shorts = "-".join(_MUTATION_SHORT_NAMES[name] for name in operators)
    current.name = f"{genome.name}-sel-{shorts}-mut"
    if not _stamp:
        return current
    return stamp_origin(
        current,
        _mutation_origin(
            "mutate_selected",
            genome,
            origin_context,
            note="components: " + ", ".join(operators),
        ),
    )


def mutate_all(
    genome: PipelineGenome,
    rate: float,
    models: list[str] | None = None,
    *,
    origin_context: EvalContext | None = None,
    _stamp: bool = True,
) -> PipelineGenome:
    """
    Apply all mutation operators to the genome in sequence.

    This function sequentially applies topology, node, prompt, fixer-genome, and
    evaluation weight mutations to the input genome, each with the given mutation
    rate. The resulting genome is a mutated version of the input, with a new name
    indicating that all mutation types were applied.

    Args:
        genome: The input pipeline genome to mutate.
        rate: The mutation rate (probability) for each individual mutation step.
        models: Optional model pool constraint — the run's routable roster. When
            given, model mutation/new nodes only draw from it (an unroutable
            model is a guaranteed-0 evaluation whose gene spreads via breeding).
        origin_context: Optional evaluation context to freeze into the child's
            CandidateOrigin (M4-A8). When omitted the origin records an
            "unknown" context, which keeps its credit in a separate, weaker
            scope until evaluated under a known one.

    Returns:
        A new PipelineGenome with all mutations applied, stamped with a
        composite ``mutate_all`` CandidateOrigin (the intermediate per-operator
        children are transient and carry no origin into the population).
    """
    current = mutate_topology(genome, rate, models, _stamp=False)
    current = mutate_node(current, rate, models, _stamp=False)
    current = mutate_prompt(current, rate, _stamp=False)
    current = mutate_fixer_genome(current, rate, _stamp=False)
    current = mutate_eval_weights(current, rate, _stamp=False)
    current.name = genome.name + "-all-mut"
    if not _stamp:
        return current
    return stamp_origin(
        current,
        _mutation_origin(
            "mutate_all",
            genome,
            origin_context,
            note="components: " + ", ".join(MUTATION_OPERATOR_NAMES),
        ),
    )
