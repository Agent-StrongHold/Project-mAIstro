"""Substrate tools — domain-agnostic DAG execution, evaluation, and hill-climbing.

Always available in chat regardless of domain. Operates on the graph substrate.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4

logger = logging.getLogger("hive.substrate_tools")


async def tool_run_workflow(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Execute a DAG by ID or name."""
    from stores import dags as dag_store

    from services.graph_runner import execute_dag

    dag_id = args.get("dag_id") or args.get("id", "")
    name = args.get("name", "")
    if not dag_id and name:
        for did, d in dag_store.items():
            if d.get("name", "").lower() == name.lower():
                dag_id = did
                break
    if dag_id not in dag_store:
        return {"error": f"Workflow '{dag_id or name}' not found."}

    dag_data = dag_store[dag_id]
    start = time.monotonic()
    result = await execute_dag(dag_data, user_id=user_id)
    elapsed = int((time.monotonic() - start) * 1000)
    nr = result.get("node_results", {})
    return {
        "status": "completed",
        "dag_id": dag_id,
        "name": dag_data.get("name"),
        "nodes_total": len(nr),
        "nodes_succeeded": sum(1 for r in nr.values() if r.get("success")),
        "elapsed_ms": elapsed,
        "node_results": {
            nid: {
                "role": r.get("role"),
                "success": r.get("success"),
                "response": r.get("response", "")[:2000],
            }
            for nid, r in nr.items()
        },
    }


async def tool_create_workflow(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Create a new executable DAG."""
    from stores import dags as dag_store

    nodes_spec = args.get("nodes", [])
    if not nodes_spec:
        return {"error": "nodes array required. Each: {name, prompt, model?}"}

    dag_id = str(uuid4())
    nodes, edges, prev_id = [], [], None
    for i, spec in enumerate(nodes_spec):
        nid = f"n{i + 1}-{str(uuid4())[:6]}"
        nodes.append(
            {
                "id": nid,
                "name": spec.get("name", f"Node {i + 1}"),
                "role": "worker",
                "kind": spec.get("kind", "llm.generate"),
                "model": spec.get("model"),
                "prompt": spec.get("prompt", ""),
            }
        )
        if prev_id:
            edges.append({"source": prev_id, "target": nid})
        prev_id = nid

    dag_store[dag_id] = {
        "id": dag_id,
        "name": args.get("name", "Untitled"),
        "description": args.get("description", ""),
        "nodes": nodes,
        "edges": edges,
        "eval_rubric": args.get("eval_rubric", {}),
        "user_context": [],
        "created_by": user_id,
    }
    return {"created": True, "dag_id": dag_id, "name": args.get("name"), "node_count": len(nodes)}


async def tool_evaluate_run(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Score output against DAG's rubric using LLM-as-judge."""
    from stores import dags as dag_store

    from services.graph_runner import _build_llm_call

    dag_id = args.get("dag_id", "")
    output = args.get("output", "")
    if dag_id not in dag_store:
        return {"error": "DAG not found"}
    rubric = dag_store[dag_id].get("eval_rubric", {})
    if not rubric.get("criteria"):
        return {"error": "No eval rubric. Use update_eval first."}

    criteria_text = "\n".join(
        f"- {c['name']} ({c.get('weight', 20)}%): {c.get('description', '')}"
        for c in rubric["criteria"]
    )
    prompt = f'Score this output against the rubric. Return JSON only: {{"scores": {{"name": 0-100}}, "total": weighted_avg, "critique": "actionable feedback"}}\n\nRUBRIC:\n{criteria_text}\n\nOUTPUT:\n{output[:4000]}'
    try:
        resp = await _build_llm_call()(
            [
                {"role": "system", "content": "Strict evaluator. JSON only."},
                {"role": "user", "content": prompt},
            ],
            model=rubric.get("judge_model", "gemini-3.5-flash"),
        )
        return {"dag_id": dag_id, "eval": json.loads(resp)}
    except Exception as e:
        return {"error": f"Eval failed: {e}"}


async def tool_update_eval(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Modify a DAG's eval rubric."""
    from stores import dags as dag_store

    dag_id = args.get("dag_id", "")
    if dag_id not in dag_store:
        return {"error": "DAG not found"}
    rubric = dag_store[dag_id].setdefault("eval_rubric", {"criteria": []})
    if "criteria" in args:
        rubric["criteria"] = args["criteria"]
    if "add_criterion" in args:
        rubric["criteria"].append(args["add_criterion"])
    if "remove_criterion" in args:
        rubric["criteria"] = [
            c for c in rubric["criteria"] if c.get("name") != args["remove_criterion"]
        ]
    if "judge_model" in args:
        rubric["judge_model"] = args["judge_model"]
    if "target_score" in args:
        rubric["target_score"] = args["target_score"]
    return {"updated": True, "dag_id": dag_id, "criteria_count": len(rubric["criteria"])}


async def tool_hill_climb(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Real hill climbing: run -> eval -> inject critique -> re-run."""
    from stores import dags as dag_store

    from services.graph_runner import execute_dag

    dag_id = args.get("dag_id", "")
    max_attempts = min(args.get("max_attempts", 3), 5)
    target_score = args.get("target_score", 90)
    if dag_id not in dag_store:
        return {"error": "DAG not found"}
    dag_data = dag_store[dag_id]
    if not dag_data.get("eval_rubric", {}).get("criteria"):
        return {"error": "No eval rubric. Use update_eval first."}

    best_score, best_result, attempts = 0, None, []
    for attempt in range(1, max_attempts + 1):
        result = await execute_dag(dag_data, user_id=user_id)
        output = "\n".join(
            r.get("response", "")
            for r in result.get("node_results", {}).values()
            if r.get("success")
        )
        ev = await tool_evaluate_run({"dag_id": dag_id, "output": output}, user_id)
        score = ev.get("eval", {}).get("total", 0)
        critique = ev.get("eval", {}).get("critique", "")
        attempts.append({"attempt": attempt, "score": score, "critique": critique})
        if score > best_score:
            best_score = score
            best_result = output
        if score >= target_score:
            break
        # THE KEY: inject critique into node prompts for next attempt
        if attempt < max_attempts and critique:
            constraint = f'\n\n--- CONSTRAINT (attempt {attempt}) ---\nEvaluator: "{critique}"\nAddress this SPECIFICALLY in your output.\n---'
            for node in dag_data.get("nodes", []):
                node["prompt"] = (node.get("prompt") or "") + constraint
            import asyncio

            await asyncio.sleep(3)  # rate-limit backoff between attempts

    return {
        "dag_id": dag_id,
        "best_score": best_score,
        "target": target_score,
        "passed": best_score >= target_score,
        "attempts": attempts,
        "best_result": (best_result or "")[:3000],
    }


async def tool_mutate_workflow(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """Structural DAG mutation: add/remove nodes, rewrite prompts."""
    from stores import dags as dag_store

    dag_id = args.get("dag_id", "")
    mut = args.get("type", "")
    if dag_id not in dag_store:
        return {"error": "DAG not found"}
    dag = dag_store[dag_id]
    nodes, edges = dag.get("nodes", []), dag.get("edges", [])

    if mut == "add_node":
        nid = f"n{len(nodes) + 1}-{str(uuid4())[:6]}"
        nodes.append(
            {
                "id": nid,
                "name": args.get("name", "New"),
                "role": "worker",
                "kind": "llm.generate",
                "prompt": args.get("prompt", ""),
                "model": args.get("model"),
            }
        )
        after = args.get("after_node_id")
        if after:
            edges.append({"source": after, "target": nid})
        dag["edges"] = edges
        return {"mutated": True, "type": "add_node", "node_id": nid}
    elif mut == "remove_node":
        tid = args.get("node_id", "")
        dag["nodes"] = [n for n in nodes if n["id"] != tid]
        dag["edges"] = [e for e in edges if e.get("source") != tid and e.get("target") != tid]
        return {"mutated": True, "type": "remove_node", "removed": tid}
    elif mut == "rewrite_prompt":
        tid = args.get("node_id", "")
        for n in nodes:
            if n["id"] == tid:
                n["prompt"] = args.get("prompt", "")
                return {"mutated": True, "type": "rewrite_prompt", "node_id": tid}
        return {"error": f"Node {tid} not found"}
    return {"error": f"Unknown type: {mut}"}


async def tool_list_workflows(
    args: dict[str, Any], user_id: str, jira_pat: str | None = None
) -> dict[str, Any]:
    """List all DAGs."""
    from stores import dags as dag_store

    return {
        "workflows": [
            {
                "id": d,
                "name": dag_store[d].get("name", ""),
                "nodes": len(dag_store[d].get("nodes", [])),
                "has_rubric": bool(dag_store[d].get("eval_rubric", {}).get("criteria")),
            }
            for d in dag_store
        ]
    }


SUBSTRATE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_workflow",
            "description": "Execute a DAG/workflow. Returns real results.",
            "parameters": {
                "type": "object",
                "properties": {"dag_id": {"type": "string"}, "name": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workflow",
            "description": "Create a new DAG. Each node: {name, prompt, model?}",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "nodes": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["name", "nodes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_run",
            "description": "Score output against DAG's rubric.",
            "parameters": {
                "type": "object",
                "properties": {"dag_id": {"type": "string"}, "output": {"type": "string"}},
                "required": ["dag_id", "output"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_eval",
            "description": "Modify DAG eval rubric: criteria, weights, examples.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dag_id": {"type": "string"},
                    "criteria": {"type": "array"},
                    "add_criterion": {"type": "object"},
                    "remove_criterion": {"type": "string"},
                    "target_score": {"type": "integer"},
                },
                "required": ["dag_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hill_climb",
            "description": "Run->eval->mutate->repeat. Real iterative improvement.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dag_id": {"type": "string"},
                    "max_attempts": {"type": "integer"},
                    "target_score": {"type": "integer"},
                },
                "required": ["dag_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mutate_workflow",
            "description": "Structural DAG mutation: add/remove/rewrite nodes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "dag_id": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["add_node", "remove_node", "rewrite_prompt"],
                    },
                    "node_id": {"type": "string"},
                    "after_node_id": {"type": "string"},
                    "name": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["dag_id", "type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workflows",
            "description": "List all DAGs.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

SUBSTRATE_TOOL_HANDLERS = {
    "run_workflow": tool_run_workflow,
    "create_workflow": tool_create_workflow,
    "evaluate_run": tool_evaluate_run,
    "update_eval": tool_update_eval,
    "hill_climb": tool_hill_climb,
    "mutate_workflow": tool_mutate_workflow,
    "list_workflows": tool_list_workflows,
}
