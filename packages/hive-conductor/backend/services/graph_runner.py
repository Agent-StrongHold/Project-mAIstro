"""Graph runner — bridges hive-conductor DAGs to maistro-core graph executor.

Converts a DAGFile dict from the store into a GraphConfig, builds an
LLM callable from settings, and runs the graph.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from typing import Any

import httpx

from maistro.http import shared_client

logger = logging.getLogger(__name__)

OnResponseHook = Callable[[dict[str, Any], httpx.Response], None]


class StubLLMNotAllowedError(RuntimeError):
    """No LLM gateway is configured and the stub opt-in is off.

    F3 (loud degraded modes): the graph runner used to hand back a
    success-shaped `{"response": "stub: no LLM configured", "done": true}`
    whenever `LITELLM_*` was unset, so a misconfigured deployment produced
    fake successes. It now refuses instead.
    """


#: Actionable message for `StubLLMNotAllowedError` — names what is unset and
#: both ways forward (configure a real gateway, or opt in to labelled stubs).
STUB_LLM_REFUSAL = (
    "No LLM gateway is configured: neither LITELLM_API_BASE nor LITELLM_PROXY_URL "
    "is set. Refusing to run against a stub LLM, because a stub answer is noise "
    "and would look like a real result. Either set LITELLM_API_BASE (with "
    "LITELLM_API_KEY) to a real gateway, or set ALLOW_STUB_LLM=true "
    "(Settings.allow_stub_llm) to explicitly opt in to clearly-labelled stub "
    "responses."
)


def llm_gateway_configured() -> bool:
    """True when a real LLM gateway base URL is configured.

    The single source of truth for "is this conductor degraded?" — used by
    `_build_llm_call` to decide whether to refuse, and by the health endpoint
    to report `degraded`.
    """
    return bool(os.environ.get("LITELLM_API_BASE") or os.environ.get("LITELLM_PROXY_URL"))


def stub_llm_allowed() -> bool:
    """True when the operator explicitly opted in to stub LLM responses.

    Fails closed: if settings cannot be loaded at all, the opt-in is off and
    `_build_llm_call` refuses rather than silently stubbing.
    """
    try:
        from config import get_settings

        return bool(get_settings().allow_stub_llm)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("allow_stub_llm_settings_unavailable: %s", exc)
        return False


# Static subprocess body. All untrusted values (system prompt, task description,
# parent context) are read from environment variables at runtime — NEVER
# templated into this source — so triple-quotes, backslashes and newlines in a
# node prompt cannot break out of a string literal and inject Python (RCE).
_NODE_SCRIPT = """
import json, os, sys
import httpx

base = os.environ.get("LITELLM_API_BASE", "").rstrip("/")
if not base.endswith("/v1"):
    base += "/v1"
key = os.environ.get("LITELLM_API_KEY", "")
model = os.environ.get("DAG_NODE_MODEL", "gemini-3.5-flash")
system = os.environ.get("DAG_NODE_SYSTEM", "")
task = os.environ.get("DAG_NODE_TASK", "")
context = os.environ.get("DAG_NODE_CONTEXT", "")
user = "Task: " + task + "\\n\\nContext:\\n" + context
r = httpx.post(
    base + "/chat/completions",
    headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    json={
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    },
    timeout=120,
)
r.raise_for_status()
data = r.json()
print(json.dumps({"content": data["choices"][0]["message"]["content"], "usage": data.get("usage")}))
"""


def _parse_node_script_output(raw_output: str) -> tuple[str, dict[str, Any] | None]:
    """Parse `_NODE_SCRIPT`'s stdout JSON envelope into (content, usage).

    Falls back to treating `raw_output` itself as the content with no usage
    if it isn't the expected JSON shape -- a malformed envelope must degrade
    gracefully, not break sandboxed execution.
    """
    try:
        envelope = json.loads(raw_output.strip())
        return str(envelope.get("content") or ""), envelope.get("usage")
    except (json.JSONDecodeError, AttributeError, TypeError):
        return raw_output.strip(), None


def _run_node_subprocess(
    node: dict[str, Any],
    task_desc: str,
    context: str,
    base_env: dict[str, str],
    execution_mode: str = "autonomous",
) -> dict[str, Any]:
    """Run a single DAG node in an isolated executor.

    Untrusted strings (prompt/task/context) are passed via env vars, not
    interpolated into source. Module-level (not a closure) so it is picklable
    for ProcessPoolExecutor.
    """
    import asyncio as _aio

    from services.hyperlight_executor import get_executor

    node_env = {
        **base_env,
        "DAG_NODE_MODEL": node.get("model", "gemini-3.5-flash"),
        "DAG_NODE_SYSTEM": node.get("prompt", "") or "",
        "DAG_NODE_TASK": task_desc,
        "DAG_NODE_CONTEXT": context[:2000],
    }
    try:
        executor = get_executor()
        result = _aio.run(
            executor.execute_node(
                _NODE_SCRIPT,
                env=node_env,
                timeout_s=120,
                allow_network=True,  # nodes need to call LiteLLM
                mode=execution_mode,
            )
        )
        if result["success"]:
            content, usage = _parse_node_script_output(result["output"])
            return {
                "role": node.get("role", "worker"),
                "response": content,
                "success": True,
                "isolation": result.get("isolation", "unknown"),
                "usage": usage,
            }
        return {
            "role": node.get("role", "worker"),
            "response": result.get("error", "")[:500],
            "success": False,
            "isolation": result.get("isolation", "unknown"),
        }
    except Exception as e:
        return {"role": node.get("role", "worker"), "response": str(e), "success": False}


async def _tool_web_search(
    tool_config: dict[str, Any], parent_outputs: dict[str, Any], task_desc: str
) -> str:
    iterate_over = tool_config.get("iterate_over", "")
    queries: list[str] = []
    if iterate_over and "." in iterate_over:
        src_node, src_field = iterate_over.split(".", 1)
        src_data = parent_outputs.get(src_node, "")
        try:
            parsed = json.loads(src_data) if isinstance(src_data, str) else src_data
            queries = parsed.get(src_field, []) if isinstance(parsed, dict) else []
        except (json.JSONDecodeError, AttributeError):
            queries = [task_desc]
    elif tool_config.get("queries_from_input"):
        template = tool_config.get("query_template", "{input}")
        queries = [template.replace("{input}", task_desc)]
    if not queries:
        queries = [task_desc]

    from services.tool_executor import web_search

    all_results = []
    max_r = tool_config.get("max_results", 5)
    for q in queries[:5]:
        sr = await web_search(q, max_results=max_r)
        all_results.append(sr)
    return json.dumps(all_results, indent=2)


async def _tool_clarify(tool_config: dict[str, Any], task_desc: str) -> str:
    from services.tool_executor import clarify

    questions = tool_config.get("questions", [])
    answers = await clarify(questions, {"input": task_desc})
    return "\n".join(
        f"Q: {q}\nA: {answers.get(str(i + 1), answers.get(q, 'Not specified'))}\n"
        for i, q in enumerate(questions)
    )


async def _tool_browse_url(tool_config: dict[str, Any]) -> str:
    from services.tool_executor import browse_url

    url = tool_config.get("url", "")
    task = tool_config.get("task", "Extract key information")
    br = await browse_url(url, task)
    return json.dumps(br, indent=2)


async def _run_tool_node(
    node: dict[str, Any],
    nid: str,
    inbound: dict[str, set[str]],
    results: dict[str, dict[str, Any]],
    task_desc: str,
) -> None:
    """Execute a tool node (in place into ``results``) instead of an LLM call."""
    role = node.get("role", "worker")
    tool_name = node.get("tool")
    try:
        from services.tool_executor import TOOLS

        tool_fn = TOOLS.get(tool_name)
        if not tool_fn:
            results[nid] = {
                "role": role,
                "response": f"Unknown tool: {tool_name}",
                "success": False,
            }
            return
        tool_config = node.get("tool_config", {})
        parent_outputs = {
            pid: results[pid]["response"]
            for pid in inbound[nid]
            if pid in results and results[pid].get("success")
        }

        if tool_name == "web_search":
            response = await _tool_web_search(tool_config, parent_outputs, task_desc)
        elif tool_name == "clarify":
            response = await _tool_clarify(tool_config, task_desc)
        elif tool_name == "browse_url":
            response = await _tool_browse_url(tool_config)
        else:
            result = await tool_fn(task_desc)
            response = json.dumps(result) if isinstance(result, dict) else str(result)
        results[nid] = {"role": role, "response": response, "success": True}
    except Exception as e:
        logger.error(f"Tool node {nid} failed: {e}")
        results[nid] = {"role": role, "response": f"Tool error: {e}", "success": False}


def _classify_node_execution(node: dict[str, Any], nid: str) -> str:
    """Classify a node's execution tier — default-deny for unconfigured nodes.

    Returns:
    - 'async': trusted, in-process (only for explicitly safe nodes)
    - 'sandbox': must run in isolated sandbox
    - 'blocked': refuse to execute (untrusted + no admin approval)
    """
    config = node.get("config", {})
    tier = config.get("execution_tier", "")
    capabilities = config.get("capabilities", [])

    is_dangerous = any(c in ("shell", "file_write", "code_exec", "browser") for c in capabilities)
    needs_secrets = any(c in ("jira_write", "deploy", "git_push") for c in capabilities)
    needs_filesystem = any(
        c in ("code_exec", "file_write", "repo_clone", "pytest") for c in capabilities
    )
    is_untrusted = config.get("untrusted", False)

    # Explicitly safe — only if declared
    if tier in ("light", "safe"):
        return "async"

    # Untrusted code MUST be approved by admin or it's blocked
    if is_untrusted:
        if config.get("tier_approved_by") != "admin":
            logger.warning("node_blocked node=%s reason=untrusted_no_approval", nid)
            return "blocked"
        return "sandbox"

    if is_dangerous or needs_secrets or needs_filesystem or tier in ("container", "heavy"):
        return "sandbox"

    # DEFAULT-DENY: unconfigured nodes get sandboxed, not trusted
    if not tier and not capabilities:
        logger.info("node_default_sandbox node=%s reason=no_tier_no_capabilities", nid)
        return "sandbox"

    return "sandbox"


def _build_dependency_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    """Return (node_map, inbound) where inbound[node] is the set of upstream node ids."""
    node_map = {n["id"]: n for n in nodes}
    inbound: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    for e in edges:
        src, dst = e.get("from_node", ""), e.get("to_node", "")
        if src and dst and src in node_map and dst in node_map:
            inbound[dst].add(src)
    return node_map, inbound


async def _run_llm_node(
    node: dict[str, Any],
    nid: str,
    inbound: dict[str, set[str]],
    results: dict[str, dict[str, Any]],
    task_desc: str,
    on_response: OnResponseHook | None = None,
) -> None:
    """Run an in-process node: a tool node, or an LLM call. Writes into ``results``."""
    role = node.get("role", "worker")

    # --- TOOL NODE: execute tool instead of LLM ---
    if node.get("tool"):
        await _run_tool_node(node, nid, inbound, results, task_desc)
        return
    # --- END TOOL NODE ---

    model = node.get("model", os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash"))
    system = node.get("prompt", "") or f"You are a {node.get('name', 'worker')} agent."
    user_content = f"Task: {task_desc}"
    parent_outputs = [
        results[pid]["response"]
        for pid in inbound[nid]
        if pid in results and results[pid].get("success")
    ]
    if parent_outputs:
        user_content += "\n\nContext from previous steps:\n" + "\n---\n".join(parent_outputs[-3:])
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    try:
        response = await _build_llm_call(on_response)(messages, model=model)
        results[nid] = {"role": role, "response": response, "success": True}
    except Exception as e:
        results[nid] = {"role": role, "response": str(e), "success": False}


def _invoke_subprocess_usage_hooks(
    subprocess_nodes: list[str],
    results: dict[str, dict[str, Any]],
    on_response: OnResponseHook | None,
) -> None:
    """After a subprocess wave's results are in, invoke `on_response` for
    every node result carrying a usage payload. Extracted from
    `_run_subprocess_wave` so this parent-process-only logic is directly
    unit-testable without needing a real `ProcessPoolExecutor` fork -- a
    sandboxed node's actual `httpx.Response` never leaves its child process,
    so a synthetic one carrying just the usage body stands in for the hook.
    """
    if on_response is None:
        return
    for nid in subprocess_nodes:
        usage = results.get(nid, {}).get("usage")
        if usage is None:
            continue
        try:
            synthetic_response = httpx.Response(200, json={"usage": usage})
            on_response({"usage": usage}, synthetic_response)
        except Exception:
            logger.warning("graph_runner_subprocess_on_response_hook_failed", exc_info=True)


async def _run_subprocess_wave(
    subprocess_nodes: list[str],
    node_map: dict[str, dict[str, Any]],
    inbound: dict[str, set[str]],
    results: dict[str, dict[str, Any]],
    task_desc: str,
    node_env: dict[str, str],
    execution_mode: str = "autonomous",
    on_response: OnResponseHook | None = None,
) -> None:
    """Run heavy/risky nodes each in their own process; write results in place.

    `on_response`, if given, is invoked afterward via
    `_invoke_subprocess_usage_hooks` -- restoring the primary usage-based
    recording path this tier skipped entirely before (ambient header
    reconciliation still isn't available here; headers aren't captured
    across the subprocess boundary).
    """
    if not subprocess_nodes:
        return
    import asyncio
    import concurrent.futures

    with concurrent.futures.ProcessPoolExecutor(max_workers=len(subprocess_nodes)) as pool:
        loop = asyncio.get_event_loop()
        futures = []
        for nid in subprocess_nodes:
            ctx = "\n---\n".join(
                results[pid]["response"]
                for pid in inbound[nid]
                if pid in results and results[pid].get("success")
            )
            futures.append(
                loop.run_in_executor(
                    pool,
                    _run_node_subprocess,
                    node_map[nid],
                    task_desc,
                    ctx,
                    node_env,
                    execution_mode,
                )
            )
        subprocess_results = await asyncio.gather(*futures)
        for nid, res in zip(subprocess_nodes, subprocess_results, strict=True):
            results[nid] = res
        _invoke_subprocess_usage_hooks(subprocess_nodes, results, on_response)


async def execute_dag(
    dag_data: dict,
    *,
    user_id: str = "",
    user_credentials: dict[str, str] | None = None,
    execution_mode: str = "autonomous",
    on_response: OnResponseHook | None = None,
) -> dict[str, Any]:
    """Execute a DAG — each node is its own process, scoped to user context. No cross-user data leakage.

    `execution_mode` is "interactive" (human watching the run) or "autonomous"
    (unattended — scheduler, optimizer, evolve harness). Autonomous is the
    default and requires gVisor-or-better sandbox isolation (ADR-093); on a
    shared-kernel-only host, sandboxed nodes refuse rather than run full-auto.

    `on_response`, if given, is forwarded to every in-process LLM node's
    `_build_llm_call` -- the additive quota-recording seam described there.
    """
    import asyncio

    nodes = dag_data.get("nodes", [])
    edges = dag_data.get("edges", [])
    if not nodes:
        return {"status": "completed", "cycles": 0, "node_results": {}}

    # Per-user scoped env — only what this user's nodes need, nothing else
    node_env = {
        "LITELLM_API_BASE": os.environ.get("LITELLM_API_BASE", ""),
        "LITELLM_API_KEY": os.environ.get("LITELLM_API_KEY", ""),
        "CHAT_DEFAULT_MODEL": os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash"),
        "DAG_USER_ID": user_id,
        "DAG_ID": dag_data.get("id", ""),
        "PATH": os.environ.get("PATH", ""),
    }
    if user_credentials:
        for k, v in user_credentials.items():
            node_env[f"USER_CRED_{k.upper()}"] = v

    task_desc = dag_data.get("description", dag_data.get("name", ""))

    # Build dependency graph
    node_map, inbound = _build_dependency_graph(nodes, edges)

    results: dict[str, dict[str, Any]] = {}
    completed: set[str] = set()

    # Execute in waves — execution strategy per node
    cycles = 0
    while len(completed) < len(nodes):
        ready = [
            nid for nid in node_map if nid not in completed and inbound[nid].issubset(completed)
        ]
        if not ready:
            break

        # Group by execution tier — uses security infrastructure
        async_nodes = []
        sandbox_nodes = []
        for nid in ready:
            tier = _classify_node_execution(node_map[nid], nid)
            if tier == "blocked":
                results[nid] = {
                    "error": "Execution blocked: untrusted node requires admin approval",
                    "success": False,
                }
                completed.add(nid)
            elif tier == "sandbox":
                sandbox_nodes.append(nid)
            else:
                async_nodes.append(nid)

        # Run sandboxed nodes (isolated execution)
        await _run_subprocess_wave(
            sandbox_nodes,
            node_map,
            inbound,
            results,
            task_desc,
            node_env,
            execution_mode,
            on_response=on_response,
        )

        # Run async nodes concurrently (light, safe — in-process, no GIL issue for I/O)
        if async_nodes:
            await asyncio.gather(
                *[
                    _run_llm_node(
                        node_map[nid], nid, inbound, results, task_desc, on_response=on_response
                    )
                    for nid in async_nodes
                ]
            )

        completed.update(ready)
        cycles += 1

    return {"status": "completed", "cycles": cycles, "node_results": results}


def genome_to_dag(genome: Any) -> dict[str, Any]:
    """Convert an evolved PipelineGenome into a DAG dict for execute_dag."""
    nodes = []
    for n in genome.topology.nodes:
        nodes.append(
            {
                "id": n.id,
                "name": f"{n.role}-{n.id[:6]}",
                "role": n.role,
                "model": n.model,
                "prompt": n.system_prompt,
                "strategy": n.strategy,
                "temperature": n.temperature,
                "max_tokens": n.max_tokens,
                "max_tool_rounds": n.max_tool_rounds,
            }
        )

    edges = []
    for e in genome.topology.edges:
        edges.append(
            {
                "id": e.id,
                "from_node": e.from_node,
                "to_node": e.to_node,
                "condition": e.condition,
            }
        )

    return {
        "name": genome.name,
        "description": f"Evolved pipeline (gen={genome.generation}, fitness={genome.fitness_score})",
        "nodes": nodes,
        "edges": edges,
        "entry_node": genome.topology.entry_node,
        "max_cycles": genome.topology.max_cycles,
        "run_scout": genome.topology.use_scout,
        "genome_id": genome.id,
        "evolved": True,
    }


async def execute_champion() -> dict[str, Any]:
    """Run the current evolution champion's pipeline through the graph executor."""
    try:
        from services.evolution import get_evolution_service

        svc = get_evolution_service()
    except RuntimeError:
        return {"status": "error", "error": "evolution service not started"}

    if svc.population is None:
        return {"status": "error", "error": "population not initialized"}

    champion = svc.population.get_champion()
    if champion is None:
        return {"status": "error", "error": "no champion yet"}

    dag_data = genome_to_dag(champion)
    result = await execute_dag(dag_data)
    result["genome_id"] = champion.id
    result["fitness"] = champion.fitness_score
    result["generation"] = champion.generation
    return result


def _build_llm_call(on_response: OnResponseHook | None = None):
    """Build the `llm_call` graph nodes/DAGs call through.

    `on_response`, if given, is invoked with the parsed body and the raw
    response right after a real (non-stub) call succeeds -- the same
    additive quota-recording seam `pm_llm_call.maistro_llm_call` /
    `conductor._call_gateway` expose in maistro-core, so `maistro.quota.recorder`
    can be wired into hive-conductor's Graph Runner traffic too. A failing
    hook is logged and swallowed since instrumentation on an already-
    successful call must never turn into a failure the caller has to handle.
    """
    import os

    base = os.environ.get("LITELLM_API_BASE") or os.environ.get("LITELLM_PROXY_URL") or ""
    raw_key = os.environ.get("LITELLM_API_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""
    model = os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash")

    if not base:
        # F3: hard-fail by default. A stub answer dressed up as a success is
        # worse than no answer — refuse unless the operator opted in.
        if not stub_llm_allowed():
            logger.error("llm_not_configured_refusing_stub")
            raise StubLLMNotAllowedError(STUB_LLM_REFUSAL)

        async def _stub_llm(messages: list[dict], **kwargs: Any) -> str:
            logger.warning("llm_stub_response_emitted (ALLOW_STUB_LLM opt-in is on)")
            # `response`/`done` keep the shape callers already parse; `stub`
            # is the unambiguous marker (same flag maistro-evolve refuses to
            # verify against, SPEC-202 signal honesty) so a stub result can
            # never be mistaken for a real one downstream.
            return json.dumps({"response": "stub: no LLM configured", "done": True, "stub": True})

        return _stub_llm

    # Ensure /v1 suffix
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    async def _httpx_llm(messages: list[dict], **kwargs: Any) -> str:
        m = kwargs.get("model", model)
        temperature = kwargs.get("temperature", 0.3)
        max_tokens = kwargs.get("max_tokens", 4096)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {raw_key}"}
        payload: dict[str, Any] = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        # Use json_schema if provided, otherwise json_object
        schema = kwargs.get("response_schema")
        if schema:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema},
            }
        else:
            payload["response_format"] = {"type": "json_object"}
        async with shared_client(timeout=120.0) as client:
            resp = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if on_response is not None:
                try:
                    on_response(data, resp)
                except Exception:
                    logger.warning("graph_runner_on_response_hook_failed", exc_info=True)
            content = data["choices"][0]["message"]["content"]
            logger.info(
                "graph_llm_response model=%s content_len=%d content_start=%s",
                m,
                len(content) if content else 0,
                (content or "")[:100],
            )
            return content or ""

    return _httpx_llm


async def execute_dag_streaming(dag_data: dict, *, on_response: OnResponseHook | None = None):
    """Yield progress events as the DAG executes, one per node completion.

    `on_response`, if given, is forwarded to the graph's `llm_call` -- see
    `_build_llm_call` for the additive quota-recording seam this exposes.
    """
    from maistro.graph.executor import run_graph
    from maistro.graph.types import GraphBlackboard, GraphConfig, GraphEdge, NodeConfig

    nodes_cfg = {}
    for n in dag_data.get("nodes", []):
        nodes_cfg[n["id"]] = NodeConfig(
            role=n.get("role", "worker"),
            name=n.get("name", n["id"]),
            model=n.get("model"),
            system_prompt=n.get("prompt"),
            temperature=0.3,
            max_tokens=4096,
        )

    edges = []
    for e in dag_data.get("edges", []):
        edges.append(
            GraphEdge(
                from_node=e["from_node"],
                to_node=e.get("to_node"),
                condition=e.get("condition"),
            )
        )

    entry_node = dag_data.get("entry_node") or (
        dag_data["nodes"][0]["id"] if dag_data.get("nodes") else ""
    )

    config = GraphConfig(
        nodes=nodes_cfg,
        edges=edges,
        entry=entry_node,
        max_cycles=dag_data.get("max_cycles", 10),
        run_scout=dag_data.get("run_scout", False),
    )

    blackboard = GraphBlackboard(
        task_objective=dag_data.get("name", "Unnamed DAG"),
        workspace=dag_data.get("workspace", "/tmp/maistro-workspace"),  # nosec B108
    )
    yield {"status": "started", "node_count": len(nodes_cfg), "entry": entry_node}

    try:
        # Inside the try so an unconfigured LLM (F3) surfaces as a structured
        # `failed` event on the stream instead of raising out of the generator.
        llm_call = _build_llm_call(on_response)
        result = await run_graph(
            task=dag_data.get("description", dag_data.get("name", "")),
            config=config,
            blackboard=blackboard,
            llm_call=llm_call,
        )
        for nr in result.node_results:
            yield {
                "status": "node_complete",
                "node_id": nr.node_id,
                "role": nr.role,
                "response": nr.selected_candidate or "",
                "success": nr.success,
            }
        yield {
            "status": "completed",
            "cycles": result.total_cycles,
            "annotations": dict(blackboard.node_annotations) if blackboard.node_annotations else {},
        }
    except Exception as exc:
        yield {"status": "failed", "error": str(exc)}
