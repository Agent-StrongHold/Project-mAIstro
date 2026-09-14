"""Per-node compatibility for pre-canonical Hive DAG definitions.

This module deliberately owns no graph traversal, dependency scheduling, Run
lifecycle, or terminal-state decisions. It adapts one legacy Hive DAG node to
the canonical ``BaseNode`` contract so ``run_durable_graph`` can remain the
only physical Graph execution authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.model_chat import ModelChatEgress
from maistro.capabilities.providers.llm_gateway import (
    MODEL_CHAT_CAPABILITY,
    GatewayEndpoint,
    ModelChatRequest,
)
from maistro.graph.nodes.base import BaseNode, NodeContext
from maistro.providers.protocols import LLMProviderRegistry, LLMRouter

logger = logging.getLogger(__name__)
OnResponseHook = Callable[[dict[str, Any], Any], None]
ModelCall = Callable[..., Awaitable[str]]
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


# This compatibility script is retained only for callers that explicitly use
# the old isolation helper. Model-backed canonical nodes never execute it: they
# cross ModelChatEgress in-process so the Invocation can name the Attempt.
_NODE_SCRIPT = """
import json, os

print(json.dumps({
    "content": os.environ.get("DAG_NODE_TASK", ""),
    "system": os.environ.get("DAG_NODE_SYSTEM", ""),
    "context": os.environ.get("DAG_NODE_CONTEXT", ""),
    "usage": None,
}))
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
    tool_config: dict[str, Any],
    parent_outputs: dict[str, Any],
    task_desc: str,
    *,
    model_call: ModelCall | None = None,
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
        if model_call is None:
            all_results.append(await web_search(query, max_results=max_r))
        else:
            all_results.append(await web_search(query, max_results=max_r, model_call=model_call))
    return json.dumps(all_results, indent=2)


async def _tool_clarify(
    tool_config: dict[str, Any], task_desc: str, *, model_call: ModelCall | None = None
) -> str:
    from services.tool_executor import clarify

    questions = tool_config.get("questions", [])
    if model_call is None:
        answers = await clarify(questions, {"input": task_desc})
    else:
        answers = await clarify(questions, {"input": task_desc}, model_call=model_call)
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
    *,
    model_call: ModelCall | None = None,
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
            response = await _tool_web_search(
                tool_config, parent_outputs, task_desc, model_call=model_call
            )
        elif tool_name == "clarify":
            response = await _tool_clarify(tool_config, task_desc, model_call=model_call)
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
    model_call: ModelCall | None = None,
) -> None:
    role = node.get("role", "worker")
    if node.get("tool"):
        await _run_tool_node(node, nid, inbound, results, task_desc, model_call=model_call)
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
        # A canonical model caller outranks the historical builder injection.
        # The latter remains usable by standalone compatibility tests, but must
        # not become an egress escape once the container wires governed effects.
        builder = (
            (lambda hook: _build_llm_call(hook, model_call=model_call))
            if model_call is not None
            else (llm_builder or _build_llm_call)
        )
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
            payload = {"usage": usage}
            on_response(payload, _GovernedResponse(payload))
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


class _GovernedResponse:
    """Small hook-compatible response view without another HTTP client seam."""

    status_code = 200

    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


def _build_llm_call(
    on_response: OnResponseHook | None = None,
    *,
    model_call: ModelCall | None = None,
):
    """Adapt the historical callable contract to a governed model caller.

    The adapter intentionally has no environment-only fallback. A caller that
    does not supply a canonical model caller cannot accidentally turn a failed
    or unconfigured physical effect into a successful compatibility result.
    """

    if model_call is None:
        # Preserve the explicit development-only stub contract for callers that
        # use this historical helper directly. Canonical nodes always supply a
        # model caller after resolving a Binding, so this cannot be a production
        # model-effect path.
        if not llm_gateway_configured() and stub_llm_allowed():

            async def _stub_llm(messages: list[dict], **kwargs: Any) -> str:
                del messages, kwargs
                logger.warning("llm_stub_response_emitted (ALLOW_STUB_LLM opt-in is on)")
                return json.dumps(
                    {"response": "stub: no LLM configured", "done": True, "stub": True}
                )

            return _stub_llm
        raise StubLLMNotAllowedError(STUB_LLM_REFUSAL)

    async def _governed_llm(messages: list[dict], **kwargs: Any) -> str:
        content = await model_call(messages, **kwargs)
        if not isinstance(content, str):
            raise RuntimeError("governed model provider returned non-text content")
        return content

    return _governed_llm


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
        effect_context: CapabilityEffectContext | None = None,
        provider_registry: LLMProviderRegistry | None = None,
        llm_router: LLMRouter | None = None,
    ) -> None:
        self._raw_node = dict(raw_node)
        self._task_desc = task_desc
        self._node_env = dict(node_env)
        self._execution_mode = execution_mode
        self._on_response = on_response
        self._llm_builder = llm_builder
        self._effect_context = effect_context
        self._provider_registry = provider_registry
        self._llm_router = llm_router

    def _binding_id(self) -> str:
        config = self._raw_node.get("config", {})
        config_map = config if isinstance(config, Mapping) else {}
        return str(
            self._raw_node.get("binding_id")
            or self._raw_node.get("model_binding_id")
            or config_map.get("binding_id")
            or config_map.get("model_binding_id")
            or ""
        ).strip()

    async def _governed_model_call(self, ctx: NodeContext) -> ModelCall:
        if (
            self._effect_context is None
            or self._provider_registry is None
            or self._llm_router is None
        ):
            raise RuntimeError("legacy DAG model node is not wired to the canonical model egress")
        binding_id = self._binding_id()
        if not binding_id:
            raise BindingNotFound(
                f"legacy DAG node {ctx.node_id!r} requires a model.chat binding_id"
            )
        base_url = (
            self._node_env.get("MAISTRO_LLM_BASE_URL")
            or self._node_env.get("LITELLM_API_BASE")
            or self._node_env.get("LITELLM_PROXY_URL")
            or os.environ.get("MAISTRO_LLM_BASE_URL")
            or os.environ.get("LITELLM_API_BASE")
            or os.environ.get("LITELLM_PROXY_URL")
            or ""
        ).strip()
        if not base_url:
            raise StubLLMNotAllowedError(STUB_LLM_REFUSAL)
        api_key = (
            self._node_env.get("MAISTRO_LLM_API_KEY")
            or self._node_env.get("LITELLM_API_KEY")
            or self._node_env.get("LITELLM_PROXY_KEY")
            or os.environ.get("MAISTRO_LLM_API_KEY")
            or os.environ.get("LITELLM_API_KEY")
            or os.environ.get("LITELLM_PROXY_KEY")
            or ""
        )
        binding = await self._effect_context.bindings.resolve(
            binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )
        egress = ModelChatEgress(
            self._effect_context,
            registry=self._provider_registry,
            router=self._llm_router,
            endpoint=GatewayEndpoint(base_url=base_url, api_key=api_key),
        )

        async def call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            selected_model = str(
                kwargs.get("model")
                or self._raw_node.get("model")
                or self._node_env.get("CHAT_DEFAULT_MODEL")
                or os.environ.get("CHAT_DEFAULT_MODEL", "gemini-3.5-flash")
            )
            request = ModelChatRequest(
                model=selected_model,
                messages=[dict(message) for message in messages],
                temperature=float(kwargs.get("temperature", 0.3)),
                max_tokens=int(kwargs.get("max_tokens", 4096)),
            )
            effect_material = json.dumps(
                {"model": selected_model, "messages": messages},
                sort_keys=True,
                default=str,
            ).encode()
            effect_key = (
                "hive.legacy_node.model_chat:" + hashlib.sha256(effect_material).hexdigest()
            )
            result = await egress.complete(
                binding=binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=effect_key,
                request=request,
            )
            if self._on_response is not None:
                try:
                    self._on_response(result.body, _GovernedResponse(result.body))
                except Exception:
                    logger.warning("graph_runner_on_response_hook_failed", exc_info=True)
            choices = result.body.get("choices")
            if not isinstance(choices, list) or not choices:
                raise RuntimeError("governed model response contained no choices")
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise RuntimeError("governed model response contained no text content")
            logger.info(
                "graph_llm_response model=%s content_len=%d content_start=%s",
                result.model,
                len(content),
                content[:100],
            )
            return content

        return call

    async def _execute(self, inputs: _LegacyInputs, ctx: NodeContext) -> _LegacyOutput:
        node_id = ctx.node_id
        parent_outputs = _context_from_inputs(inputs)
        tier = _classify_node_execution(self._raw_node, node_id)
        if tier == "blocked":
            raise PermissionError("Execution blocked: untrusted node requires admin approval")

        governed_model_call = None
        # Browser-only and generic tool nodes do not need model authorization.
        # Clarification and grounded-search fallbacks do, as do ordinary model
        # nodes; resolve the Binding lazily at the canonical node boundary for
        # those paths only.
        tool_name = self._raw_node.get("tool")
        needs_model = not tool_name or tool_name == "clarify"
        if self._effect_context is not None and needs_model:
            governed_model_call = await self._governed_model_call(ctx)
        elif self._effect_context is not None and tool_name == "web_search":

            async def lazy_governed_model_call(
                messages: list[dict[str, Any]], **kwargs: Any
            ) -> str:
                # Search providers (Brave/Serper/Tavily/browser) do not need a
                # model Binding. Resolve one only if grounded search is the
                # actual fallback that performs model work.
                model_call = await self._governed_model_call(ctx)
                return await model_call(messages, **kwargs)

            governed_model_call = lazy_governed_model_call

        # The subprocess helper is a legacy isolation compatibility seam, not a
        # model provider. Production model nodes use the governed caller even
        # when their old execution tier says "sandbox".
        if tier == "sandbox" and governed_model_call is None and self._llm_builder is None:
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
                model_call=governed_model_call,
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
