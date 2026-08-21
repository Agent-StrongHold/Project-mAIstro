from __future__ import annotations

from typing import Any

from .types import EvalResult, PipelineGenome


def extract_signal(
    genome: PipelineGenome,
    eval_results: list[EvalResult],
) -> dict[str, Any]:
    if not eval_results:
        return {"weakest_benchmark": None, "score": 0.0, "suggestion": "no eval results"}

    worst = min(eval_results, key=lambda r: r.score)
    weakest_node_id: str | None = None
    if genome.topology.nodes:
        # Benchmarks execute the entry node's prompt (benchmarks.prompt_builder),
        # so a weak score points at the entry node, not at any other node.
        weakest_node_id = genome.topology.entry_node
        if not any(n.id == weakest_node_id for n in genome.topology.nodes):
            weakest_node_id = genome.topology.nodes[0].id

    return {
        "weakest_benchmark": worst.benchmark,
        "score": worst.score,
        "suggestion": f"Improve {worst.benchmark} performance (current: {worst.score:.3f})",
        "weakest_node_id": weakest_node_id,
    }


async def optimize_topology(
    genome: PipelineGenome,
    signal: dict[str, Any],
    llm_call: Any = None,
) -> dict[str, Any]:
    """
    Optimize the topology of a pipeline genome based on evaluation signals.

    This function generates suggestions for improving the pipeline topology,
    either by leveraging an LLM call or falling back to a heuristic approach.

    Args:
        genome: The pipeline genome containing the current topology to optimize.
        signal: A dictionary containing evaluation signals such as the weakest benchmark,
            score, and suggestions for improvement.
        llm_call: An optional async function to call an LLM for generating optimization
            suggestions. If not provided, a heuristic suggestion is returned.

    Returns:
        A dictionary containing the optimization suggestion and its source (either "llm" or "heuristic").
    """
    meta_prompt = (
        f"You are an expert at optimizing AI agent pipeline topologies.\n"
        f"The pipeline scored {signal.get('score', 0):.3f} on {signal.get('weakest_benchmark', 'unknown')}.\n"
        f"Current topology has {len(genome.topology.nodes)} nodes and {len(genome.topology.edges)} edges.\n"
        f"Entry node strategy: {genome.topology.nodes[0].strategy if genome.topology.nodes else 'none'}\n"
        f"Suggestion: {signal.get('suggestion', '')}\n\n"
        f"Suggest topology improvements as JSON: "
        f'{{"add_node": {{"role": "...", "strategy": "..."}}, "remove_node_id": "...", "reason": "..."}}'
    )

    if llm_call is not None:
        try:
            result = await llm_call(meta_prompt)
            return {"suggestion": result, "source": "llm"}
        except Exception:
            pass

    return {
        "suggestion": f"Consider adding a scout node to improve {signal.get('weakest_benchmark', 'general')} performance.",
        "source": "heuristic",
    }
