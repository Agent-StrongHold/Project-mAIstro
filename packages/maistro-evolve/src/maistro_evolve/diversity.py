from __future__ import annotations

import hashlib
import math
import random
import uuid
from datetime import UTC, datetime

from .fixer_genome import random_fixer_genome
from .mutate import MODEL_REGISTRY, STRATEGY_LIST
from .types import (
    DAGEdgeGenome,
    DAGTopology,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _fresh_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def trait_vector(genome: PipelineGenome) -> list[float]:
    nodes = genome.topology.nodes
    if not nodes:
        return [0.0] * 8

    node_count = float(len(nodes))
    avg_temp = sum(n.temperature for n in nodes) / node_count
    avg_max_tokens = sum(n.max_tokens for n in nodes) / node_count

    model_hashes: list[float] = []
    for n in nodes:
        h = hashlib.sha256(n.model.encode()).hexdigest()
        model_hashes.append(int(h[:8], 16) / 0xFFFFFFFF)
    avg_model_hash = sum(model_hashes) / len(model_hashes)

    strategy_counts: dict[str, float] = dict.fromkeys(STRATEGY_LIST, 0.0)
    for n in nodes:
        if n.strategy in strategy_counts:
            strategy_counts[n.strategy] += 1.0
    for s in strategy_counts:
        strategy_counts[s] /= node_count

    edge_count = float(len(genome.topology.edges))
    max_cycles = float(genome.topology.max_cycles)
    beam_width = float(genome.topology.beam_width)

    return [
        node_count,
        avg_temp,
        avg_max_tokens / 16384.0,
        avg_model_hash,
        strategy_counts.get("react", 0.0),
        strategy_counts.get("plan_execute", 0.0),
        strategy_counts.get("direct", 0.0),
        strategy_counts.get("delegate", 0.0),
        edge_count,
        max_cycles / 50.0,
        beam_width / 5.0,
    ]


def _euclidean(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def population_diversity(population: list[PipelineGenome]) -> float:
    if len(population) < 2:
        return 0.0
    vectors = [trait_vector(g) for g in population]
    total = 0.0
    count = 0
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            total += _euclidean(vectors[i], vectors[j])
            count += 1
    return total / count if count > 0 else 0.0


def _random_genome(models: list[str] | None = None) -> PipelineGenome:
    """``models`` pins every node to the run's routable roster (an unroutable
    model is a guaranteed-0 evaluation); default is the generic MODEL_REGISTRY."""
    pool = models or MODEL_REGISTRY
    node_count = random.randint(2, 6)
    nodes: list[NodeGenome] = []
    for _ in range(node_count):
        nodes.append(
            NodeGenome(
                id=_new_id(),
                role=random.choice(["queen", "worker", "scout", "drone", "guard"]),
                strategy=random.choice(STRATEGY_LIST),
                model=random.choice(pool),
                temperature=round(random.uniform(0.0, 1.0), 2),
                max_tokens=random.choice([256, 512, 1024, 2048, 4096, 8192, 16384]),
                system_prompt="You are a helpful agent.",
                max_tool_rounds=random.randint(1, 20),
                fixer=random_fixer_genome(),
            )
        )

    edges: list[DAGEdgeGenome] = []
    for i in range(len(nodes) - 1):
        edges.append(
            DAGEdgeGenome(
                id=_new_id(),
                from_node=nodes[i].id,
                to_node=nodes[i + 1].id,
                condition=None,
            )
        )

    topo = DAGTopology(
        nodes=nodes,
        edges=edges,
        entry_node=nodes[0].id,
        max_cycles=random.randint(1, 50),
        beam_width=random.randint(1, 5),
        use_scout=random.choice([True, False]),
    )

    weights = {}
    fields = list(EvalWeights.model_fields.keys())
    raw = [random.random() for _ in fields]
    total = sum(raw)
    for fname, val in zip(fields, raw, strict=True):
        weights[fname] = round(val / total, 4)

    ts = _fresh_timestamp()
    return PipelineGenome(
        id=_new_id(),
        name=f"spawn-{uuid.uuid4().hex[:6]}",
        topology=topo,
        eval_weights=EvalWeights(**weights),
        harness_params={},
        fitness_score=None,
        eval_scores={},
        generation=0,
        parent_a_id=None,
        parent_b_id=None,
        created_at=ts,
        updated_at=ts,
    )


def emergency_spawn(
    population: list[PipelineGenome],
    count: int,
    models: list[str] | None = None,
) -> list[PipelineGenome]:
    return [_random_genome(models) for _ in range(count)]
