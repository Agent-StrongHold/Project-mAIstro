"""Compatibility facade for Hive DAG execution.

Graph traversal and execution authority live in ``canonical_dag_runner`` and
``maistro.graph.durable_runs``. This module keeps the historical import path
for product callers while exposing only per-node compatibility helpers from
``legacy_dag_node``. It intentionally contains no dependency scheduler,
process-pool fan-out, or terminal-state implementation (#835).
"""

from __future__ import annotations

from typing import Any

from services.canonical_dag_runner import execute_dag as _canonical_execute_dag
from services.canonical_dag_runner import genome_to_dag
from services.legacy_dag_node import (
    STUB_LLM_REFUSAL,
    StubLLMNotAllowedError,
    _NODE_SCRIPT,
    _build_dependency_graph,
    _build_llm_call,
    _classify_node_execution,
    _invoke_subprocess_usage_hooks,
    _parse_node_script_output,
    _run_llm_node,
    _run_node_subprocess,
    _run_subprocess_wave,
    _run_tool_node,
    llm_gateway_configured,
    stub_llm_allowed,
)


async def execute_dag(dag_data: dict, **kwargs: Any) -> dict[str, Any]:
    """Compatibility call path backed by the canonical durable Graph executor."""
    return await _canonical_execute_dag(
        dag_data,
        llm_builder=_build_llm_call,
        **kwargs,
    )


async def execute_dag_streaming(dag_data: dict, **kwargs: Any):
    """Project canonical Run/NodeRun outcomes onto the historical websocket shape."""
    entry = dag_data.get("entry_node") or (
        dag_data.get("nodes", [{}])[0].get("id") if dag_data.get("nodes") else ""
    )
    yield {
        "status": "started",
        "node_count": len(dag_data.get("nodes", [])),
        "entry": entry,
    }
    try:
        result = await execute_dag(dag_data, **kwargs)
    except Exception as exc:
        yield {"status": "failed", "error": str(exc)}
        return

    for node_id, node_result in result.get("node_results", {}).items():
        yield {
            "status": "node_complete",
            "node_id": node_id,
            "role": node_result.get("role", "worker"),
            "response": node_result.get("response", ""),
            "success": bool(node_result.get("success")),
            "run_id": result.get("run_id"),
        }

    terminal = result.get("status", "failed")
    if terminal == "completed":
        yield {
            "status": "completed",
            "run_id": result.get("run_id"),
            "cycles": result.get("cycles", 0),
            "annotations": result.get("annotations", {}),
        }
    else:
        yield {
            "status": terminal,
            "run_id": result.get("run_id"),
            "error": result.get("error", f"canonical Run ended {terminal}"),
        }


async def execute_champion() -> dict[str, Any]:
    """Run the current evolution champion through the same canonical DAG adapter."""
    try:
        from services.evolution import get_evolution_service

        service = get_evolution_service()
    except RuntimeError:
        return {"status": "error", "error": "evolution service not started"}
    if service.population is None:
        return {"status": "error", "error": "population not initialized"}
    champion = service.population.get_champion()
    if champion is None:
        return {"status": "error", "error": "no champion yet"}
    result = await execute_dag(genome_to_dag(champion))
    result["genome_id"] = champion.id
    result["fitness"] = champion.fitness_score
    result["generation"] = champion.generation
    return result


__all__ = [
    "STUB_LLM_REFUSAL",
    "StubLLMNotAllowedError",
    "execute_champion",
    "execute_dag",
    "execute_dag_streaming",
    "genome_to_dag",
    "llm_gateway_configured",
    "stub_llm_allowed",
]
