"""Per-node compatibility for pre-canonical Hive DAG definitions.

This module deliberately owns no graph traversal, dependency scheduling, Run
lifecycle, or terminal-state decisions. It adapts one legacy Hive DAG node to
the canonical ``BaseNode`` contract so ``run_durable_graph`` can remain the
only physical Graph execution authority.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Mapping
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, ConfigDict

from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.http import shared_client

logger = logging.getLogger(__name__)
OnResponseHook = Callable[[dict[str, Any], httpx.Response], None]
_CONTEXT_PREFIX = "__hive_context__::"


class StubLLMNotAllowedError(RuntimeError):
    """No LLM gateway is configured and the explicit stub opt-in is off."""


STUB_LLM_REFUSAL = (
    "No LLM gateway is configured: neither LITELLM_API_BASE nor LITELLM_PROXY_URL "
    "is set. Refusing to run against a stub LLM, because a stub answer is noise "
    "and would look like a real result. Either set LITELLM_API_BASE (with "
    "LITELLM_API_KEY) to a real gateway, or set ALLOW_STUB_LLM=true "
    "(Settings.allow_stub_llm) to explicitly opt in to clearly-labelled stub "
    "responses."
)


def llm_gateway_configured() -> bool:
    return bool(os.environ.get("LITELLM_API_BASE") or os.environ.get("LITELLM_PROXY_URL"))


def stub_llm_allowed() -> bool:
    try:
        from config import get_settings

        return bool(get_settings().allow_stub_llm)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("allow_stub_llm_settings_unavailable: %s", exc)
        return False


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
    """Execute one compatibility node inside the configured isolation provider."""
    import asyncio as _aio

    from services.hyperlight_executor import get_executor

    model = node.get("model", "gemini-3.5-flash")
    node_env = {
        **base_env,
        "DAG_NODE_MODEL": model,
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
                allow_network=True,
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
                "model": model,
            }
        return {
            "role": node.get("role", "worker"),
            "response": result.get("error", "")[:500],
            "success": False,
            "isolation": result.get("isolation", "unknown"),
            "model": model,
        }
    except Exception as exc:
        return {
            "role": node.get("role", "worker"),
            "response": str(exc),
            "success": False,
            "model": model,
        }


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
    for query in queries[:5]:
        all_results.append(await web_search(query, max_results=max_r))
    return json.dumps(all_results, indent=2)


async def _tool_clarify(tool_config: dict[str, Any], task_desc: str) -> str:
    from services.tool_executor import clarify

    questions = tool_config.get("questions", [])
    answers = await clarify(questions, {"input": task_desc})
    return "\n".join(
        f"Q: {question}\nA: {answers.get(str(index + 1), answers.get(question, 'Not specified'))}\n"
        for index, question in enumerate(questions)
    )


async def _tool_browse_url(tool_config: dict[str, Any]) -> str:
    from services.tool_executor import browse_url

    result = await browse_url(
        tool_config.get("url", ""),
        tool_config.get("task", "Extract key information"),
    )
    return json.dumps(result, indent=2)


async def _run_tool_node(
    node: dict[str, Any],
    nid: str,
    inbound: dict[str, set[str]],
    results: dict[str, dict[str, Any]],
    task_desc: str,
) -> None:
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
            for pid in inbound.get(nid, set())
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
    except Exception as exc:
        logger.error("Tool node %s failed: %s", nid, exc)
        results[nid] = {"role": role, "response": f"Tool error: {exc}", "success": False}


def _classify_node_execution(node: dict[str, Any], nid: str) -> str:
    """Preserve the existing per-node isolation classification during convergence.

    M2 #845 owns replacing request/config-declared elevation with host-authorized
    policy. #835 removes the second graph scheduler without weakening the
    current per-node isolation floor underneath it.
    """
    config = node.get("config", {})
    tier = config.get("execution_tier", "")
    capabilities = config.get("capabilities", [])
    dangerous = any(c in ("shell", "file_write", "code_exec", "browser") for c in capabilities)
    needs_secrets = any(c in ("jira_write", "deploy", "git_push") for c in capabilities)
    needs_filesystem = any(
        c in ("code_exec", "file_write", "repo_clone", "pytest") for c in capabilities
    )
    if tier in ("light", "safe"):
        return "async"
    if config.get("untrusted", False):
        if config.get("tier_approved_by") != "admin":
            logger.warning("node_blocked node=%s reason=untrusted_no_approval", nid)
            return "blocked"
        return "sandbox"
    if dangerous or needs_secrets or needs_filesystem or tier in ("container", "heavy"):
        return "sandbox"
    if not tier and not capabilities:
        logger.info("node_default_sandbox node=%s reason=no_tier_no_capabilities", nid)
        return "sandbox"
    return "sandbox"


def _build_dependency_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    """Compatibility-only dependency metadata; never used to schedule a Graph."""
    node_map = {node["id"]: node for node in nodes}
    inbound: dict[str, set[str]] = {node["id"]: set() for node in nodes}
    for edge in edges:
        src, dst = edge.get("from_node", ""), edge.get("to_node", "")
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
    llm_builder: Callable[[OnResponseHook | None], Any] | None = None,
) -> None:
    role = node.get("role", "worker")
    if node.get("tool"):
        await _run_tool_node(node, nid, inbound, results, task_desc)
        return
    model = node.get("model", os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash"))
    system = node.get("prompt", "") or f"You are a {node.get('name', 'worker')} agent."
    user_content = f"Task: {task_desc}"
    parent_outputs = [
        results[pid]["response"]
        for pid in inbound.get(nid, set())
        if pid in results and results[pid].get("success")
    ]
    if parent_outputs:
        user_content += "\n\nContext from previous steps:\n" + "\n---\n".join(parent_outputs[-3:])
    try:
        builder = llm_builder or _build_llm_call
        response = await builder(on_response)(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            model=model,
        )
        results[nid] = {"role": role, "response": response, "success": True, "model": model}
    except Exception as exc:
        results[nid] = {"role": role, "response": str(exc), "success": False, "model": model}


def _invoke_subprocess_usage_hooks(
    subprocess_nodes: list[str],
    results: dict[str, dict[str, Any]],
    on_response: OnResponseHook | None,
) -> None:
    if on_response is None:
        return
    for nid in subprocess_nodes:
        usage = results.get(nid, {}).get("usage")
        if usage is None:
            continue
        try:
            response = httpx.Response(200, json={"usage": usage})
            on_response({"usage": usage}, response)
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
    """Compatibility helper retained for tests; canonical execution never calls it."""
    for nid in subprocess_nodes:
        context = "\n---\n".join(
            results[pid]["response"]
            for pid in inbound.get(nid, set())
            if pid in results and results[pid].get("success")
        )
        results[nid] = await asyncio.to_thread(
            _run_node_subprocess,
            node_map[nid],
            task_desc,
            context,
            node_env,
            execution_mode,
        )
    _invoke_subprocess_usage_hooks(subprocess_nodes, results, on_response)


def _build_llm_call(on_response: OnResponseHook | None = None):
    base = os.environ.get("LITELLM_API_BASE") or os.environ.get("LITELLM_PROXY_URL") or ""
    raw_key = os.environ.get("LITELLM_API_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""
    model = os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash")
    if not base:
        if not stub_llm_allowed():
            logger.error("llm_not_configured_refusing_stub")
            raise StubLLMNotAllowedError(STUB_LLM_REFUSAL)

        async def _stub_llm(messages: list[dict], **kwargs: Any) -> str:
            logger.warning("llm_stub_response_emitted (ALLOW_STUB_LLM opt-in is on)")
            return json.dumps({"response": "stub: no LLM configured", "done": True, "stub": True})

        return _stub_llm
    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    async def _httpx_llm(messages: list[dict], **kwargs: Any) -> str:
        selected_model = kwargs.get("model", model)
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.3),
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        schema = kwargs.get("response_schema")
        payload["response_format"] = (
            {"type": "json_schema", "json_schema": {"name": "output", "schema": schema}}
            if schema
            else {"type": "json_object"}
        )
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {raw_key}"}
        async with shared_client(timeout=120.0) as client:
            response = await client.post(f"{base}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            if on_response is not None:
                try:
                    on_response(data, response)
                except Exception:
                    logger.warning("graph_runner_on_response_hook_failed", exc_info=True)
            content = data["choices"][0]["message"]["content"]
            logger.info(
                "graph_llm_response model=%s content_len=%d content_start=%s",
                selected_model,
                len(content) if content else 0,
                (content or "")[:100],
            )
            return content or ""

    return _httpx_llm


class _LegacyInputs(BaseModel):
    model_config = ConfigDict(extra="allow")


class _LegacyOutput(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    response: str
    model: str | None = None
    isolation: str | None = None


def _context_from_inputs(inputs: BaseModel | Mapping[str, Any]) -> dict[str, str]:
    raw = inputs.model_dump() if isinstance(inputs, BaseModel) else dict(inputs)
    return {
        key[len(_CONTEXT_PREFIX) :]: str(value)
        for key, value in raw.items()
        if key.startswith(_CONTEXT_PREFIX)
    }


def _carry_context(
    inputs: BaseModel | Mapping[str, Any], node_id: str, response: str
) -> dict[str, str]:
    raw = inputs.model_dump() if isinstance(inputs, BaseModel) else dict(inputs)
    carried = {key: str(value) for key, value in raw.items() if key.startswith(_CONTEXT_PREFIX)}
    carried[f"{_CONTEXT_PREFIX}{node_id}"] = response
    return carried


class LegacyConductorNode(BaseNode[_LegacyInputs, _LegacyOutput]):
    """Execute exactly one legacy Hive node under a canonical NodeRun/Attempt."""

    kind: ClassVar[str] = "hive.legacy_node"
    input_schema: ClassVar[type[BaseModel]] = _LegacyInputs
    output_schema: ClassVar[type[BaseModel]] = _LegacyOutput
    display_name: ClassVar[str] = "Hive legacy node adapter"
    description: ClassVar[str] = "Compatibility adapter; canonical runtime owns traversal."
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        *,
        raw_node: dict[str, Any],
        task_desc: str,
        node_env: dict[str, str],
        execution_mode: str,
        on_response: OnResponseHook | None,
        llm_builder: Callable[[OnResponseHook | None], Any] | None = None,
    ) -> None:
        self._raw_node = dict(raw_node)
        self._task_desc = task_desc
        self._node_env = dict(node_env)
        self._execution_mode = execution_mode
        self._on_response = on_response
        self._llm_builder = llm_builder

    async def _execute(self, inputs: _LegacyInputs, ctx: NodeContext) -> _LegacyOutput:
        node_id = ctx.node_id
        parent_outputs = _context_from_inputs(inputs)
        tier = _classify_node_execution(self._raw_node, node_id)
        if tier == "blocked":
            raise PermissionError("Execution blocked: untrusted node requires admin approval")

        if tier == "sandbox":
            context = "\n---\n".join(parent_outputs.values())
            result = await asyncio.to_thread(
                _run_node_subprocess,
                self._raw_node,
                self._task_desc,
                context,
                self._node_env,
                self._execution_mode,
            )
            _invoke_subprocess_usage_hooks([node_id], {node_id: result}, self._on_response)
        else:
            scratch: dict[str, dict[str, Any]] = {
                source: {"response": value, "success": True}
                for source, value in parent_outputs.items()
            }
            inbound = {node_id: set(parent_outputs)}
            await _run_llm_node(
                self._raw_node,
                node_id,
                inbound,
                scratch,
                self._task_desc,
                on_response=self._on_response,
                llm_builder=self._llm_builder,
            )
            result = scratch[node_id]

        if not result.get("success"):
            raise RuntimeError(str(result.get("response") or result.get("error") or "node failed"))
        response = str(result.get("response") or "")
        return _LegacyOutput.model_validate(
            {
                "role": str(result.get("role") or self._raw_node.get("role") or "worker"),
                "response": response,
                "model": result.get("model") or self._raw_node.get("model"),
                "isolation": result.get("isolation"),
                **_carry_context(inputs, node_id, response),
            }
        )
