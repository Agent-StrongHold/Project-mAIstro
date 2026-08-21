from __future__ import annotations

import random
import uuid
from copy import deepcopy
from datetime import UTC, datetime

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


def mutate_topology(
    genome: PipelineGenome, rate: float, models: list[str] | None = None
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

    return PipelineGenome(
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


def mutate_node(
    genome: PipelineGenome, rate: float, models: list[str] | None = None
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
    return PipelineGenome(
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


def mutate_prompt(genome: PipelineGenome, rate: float) -> PipelineGenome:
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
    return PipelineGenome(
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


def mutate_eval_weights(genome: PipelineGenome, rate: float) -> PipelineGenome:
    if random.random() > rate:
        return PipelineGenome(
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
    return PipelineGenome(
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


def mutate_fixer_genome(genome: PipelineGenome, rate: float) -> PipelineGenome:
    """Apply `_mutate_one_fixer` to every node that carries a FixerGenome. Nodes
    without one (genomes predating ADR-070126-6386 v2, or non-fixer roles) are
    left untouched — this operator only mutates the RSI-fixer strategy layer."""
    topo = deepcopy(genome.topology)
    for node in topo.nodes:
        if node.fixer is not None:
            node.fixer = _mutate_one_fixer(node.fixer, rate)
    return PipelineGenome(
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


def mutate_all(
    genome: PipelineGenome, rate: float, models: list[str] | None = None
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

    Returns:
        A new PipelineGenome with all mutations applied.
    """
    current = mutate_topology(genome, rate, models)
    current = mutate_node(current, rate, models)
    current = mutate_prompt(current, rate)
    current = mutate_fixer_genome(current, rate)
    current = mutate_eval_weights(current, rate)
    current.name = genome.name + "-all-mut"
    return current
