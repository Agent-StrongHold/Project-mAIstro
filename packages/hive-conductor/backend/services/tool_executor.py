"""Tool-enabled DAG node executor.

Nodes can now declare tools they need. The executor provides:
  - web_search: real Playwright-driven Google/DuckDuckGo search
  - browse_url: fetch and summarize a real URL
  - clarify: multi-turn Q&A to gather requirements before generating

This replaces the naive "ask LLM to pretend it researched" pattern.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

from maistro.agents.tool_dispatch import ToolCallExecutor
from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from maistro.http import shared_client
from maistro.types.tool import ToolCall

if TYPE_CHECKING:
    from maistro.capabilities.admitted_model import AdmittedModelCalls

ModelCall = Callable[[ModelChatRequest], Awaitable[str]]

logger = logging.getLogger("hive.tool_executor")


async def web_search(
    query: str, max_results: int = 5, *, model_call: ModelCall | None = None
) -> dict[str, Any]:
    """Real web search via Brave Search API (primary), with fallbacks."""
    # Brave Search (fast, real results, free tier)
    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if brave_key:
        return await _brave_search(query, max_results, brave_key)

    # Try Serper (fast, no browser needed)
    serper_key = os.environ.get("SERPER_API_KEY", "")
    if serper_key:
        return await _serper_search(query, max_results, serper_key)

    # Try Tavily
    tavily_key = os.environ.get("TAVILY_API_KEY", "")
    if tavily_key:
        return await _tavily_search(query, max_results, tavily_key)

    # Fallback: BrowserClient (Playwright + browser-use)
    try:
        from maistro.tools.browser import BrowserClient

        client = BrowserClient()
        result = await client.search_web(query, max_results=max_results)
        await client.aclose()
        return {
            "query": query,
            "summary": result.summary,
            "citations": [
                {"title": c.title, "url": c.url, "snippet": c.snippet} for c in result.citations
            ],
            "source": result.source,
        }
    except Exception as e:
        logger.warning(f"BrowserClient failed for '{query}': {e}")

    # Last resort: use Gemini with grounding (search built into the model)
    return await _gemini_grounded_search(query, max_results, model_call=model_call)


def _ssrf_blocked(url: str) -> str | None:
    """Return a reason if ``url`` is unsafe to fetch (SSRF), else None.

    Blocks non-http(s) schemes and any host that resolves to a non-public
    address — loopback, private ranges, link-local (incl. the 169.254.169.254
    cloud-metadata endpoint), and reserved space — so `browse_url`, exposed to
    chat users, can't be turned into a request forgery against internal services.
    """
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return "unparseable URL"
    if parsed.scheme not in ("http", "https"):
        return f"scheme {parsed.scheme!r} not allowed (http/https only)"
    host = parsed.hostname
    if not host:
        return "URL has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return f"cannot resolve host {host!r}"
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if not ip.is_global or ip.is_reserved:
            return f"host {host!r} resolves to non-public address {ip}"
    return None


async def _resolve_safe_url(url: str, *, max_redirects: int = 5) -> str:
    """Follow redirects manually, re-running the SSRF check at EVERY hop, and
    return the final (non-redirecting) URL.

    Checking only the initial URL is not enough: a public URL can 30x-redirect to
    an internal or cloud-metadata host, and following that redirect would be the
    forged request. Raises PermissionError if any hop — including redirect targets
    — resolves to a non-public address.
    """
    from urllib.parse import urljoin

    current = url
    for _ in range(max_redirects + 1):
        blocked = _ssrf_blocked(current)
        if blocked:
            raise PermissionError(blocked)
        async with shared_client(timeout=15.0, follow_redirects=False) as c:
            resp = await c.get(current)
        location = resp.headers.get("location")
        if resp.is_redirect and location:
            current = urljoin(current, location)
            continue
        return current
    raise PermissionError("too many redirects")


async def browse_url(url: str, task: str = "Extract key facts and quotes") -> dict[str, Any]:
    """Fetch and summarize a real URL."""
    try:
        # Validate the whole redirect chain up front; both fetch paths below then
        # use this final, already-validated URL with redirects disabled.
        safe_url = await _resolve_safe_url(url)
    except PermissionError as e:
        return {"url": url, "error": f"blocked (SSRF protection): {e}"}
    except Exception as e:
        return {"url": url, "error": f"could not resolve URL safely: {e}"}
    try:
        from maistro.tools.browser import BrowserClient

        client = BrowserClient()
        result = await client.browse(safe_url, task)
        await client.aclose()
        return {
            "url": safe_url,
            "title": result.title,
            "text": result.text,
            "duration_ms": result.duration_ms,
        }
    except Exception:
        # Fallback: simple HTTP fetch (redirects disabled — safe_url is final).
        try:
            async with shared_client(timeout=15.0, follow_redirects=False) as c:
                r = await c.get(safe_url)
                text = r.text[:5000]
                return {"url": safe_url, "title": safe_url, "text": text, "duration_ms": 0}
        except Exception as e2:
            return {"url": safe_url, "error": str(e2)}


async def clarify(
    questions: list[str], context: dict[str, Any], *, model_call: ModelCall | None = None
) -> dict[str, str]:
    """Multi-turn clarification — ask questions, get answers from context or LLM.

    In production, this would be interactive. For DAG execution, we use the
    input context to answer clarifying questions, or generate reasonable defaults.
    """
    if model_call is None:
        raise RuntimeError("clarify requires the caller's governed model capability")

    prompt = (
        "You are helping clarify requirements for a creative project.\n"
        f"Original request: {context.get('input', '')}\n\n"
        "Answer each question with specific, detailed answers. "
        "If the original request doesn't specify, make a creative choice "
        "that would result in high-quality output.\n\n"
        "Questions:\n"
        + "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
        + "\n\nAnswer each question in detail (2-3 sentences each). "
        'Output JSON: {"answers": {"1": "...", "2": "...", ...}}'
    )

    content = await model_call(
        ModelChatRequest(
            model=os.environ.get("CHAT_DEFAULT_MODEL", "chat"),
            messages=[{"role": "user", "content": prompt}],
            temperature=None,
            response_format={"type": "json_object"},
        )
    )
    data = json.loads(content)
    if not isinstance(data, dict) or not isinstance(data.get("answers", data), dict):
        raise RuntimeError("clarification model returned a non-object answers payload")
    answers = data.get("answers", data)
    resolved: dict[str, str] = {}
    for index, question in enumerate(questions, start=1):
        answer = answers.get(str(index), answers.get(question))
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("clarification model omitted a required text answer")
        resolved[str(index)] = answer
    return resolved


async def _brave_search(query: str, max_results: int, api_key: str) -> dict[str, Any]:
    """Web search via Brave Search API. Rate limited to 1 req/sec (free tier)."""
    await asyncio.sleep(1.1)  # Free tier: 1 req/sec
    try:
        async with shared_client(timeout=15.0) as client:
            r = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
                params={"q": query, "count": max_results},
            )
            r.raise_for_status()
            data = r.json()
            results = data.get("web", {}).get("results", [])[:max_results]
            citations = [
                {
                    "title": o.get("title", ""),
                    "url": o.get("url", ""),
                    "snippet": o.get("description", "")[:200],
                }
                for o in results
            ]
            summary = " ".join(c["snippet"] for c in citations if c["snippet"])
            return {
                "query": query,
                "summary": summary[:500],
                "citations": citations,
                "source": "brave",
            }
    except Exception as e:
        logger.warning(f"Brave search failed for '{query}': {e}")
        return {"query": query, "summary": "", "citations": [], "source": "error", "error": str(e)}


async def _gemini_grounded_search(
    query: str, max_results: int, *, model_call: ModelCall | None = None
) -> dict[str, Any]:
    """Use Gemini model with search grounding via LiteLLM gateway."""
    if model_call is None:
        raise RuntimeError("grounded search requires the caller's governed model capability")

    prompt = (
        f"Search the web for: {query}\n\n"
        f"Return the top {max_results} most relevant results you find. "
        "For each result provide: title, URL, and a 1-2 sentence snippet. "
        "Then write a 3-sentence summary synthesizing the findings.\n\n"
        'Output JSON: {"summary": str, "citations": [{"title": str, "url": str, "snippet": str}]}'
    )

    content = await model_call(
        ModelChatRequest(
            model=os.environ.get("CHAT_DEFAULT_MODEL", "chat"),
            messages=[
                {
                    "role": "system",
                    "content": "You are a web research assistant. Search for real, current information. Cite real URLs you know exist. If you're not sure a URL is real, don't include it.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=None,
            response_format={"type": "json_object"},
        )
    )
    data = json.loads(content)
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("summary"), str)
        or not isinstance(data.get("citations"), list)
    ):
        raise RuntimeError("grounded search model returned invalid citations")
    return {
        "query": query,
        "summary": data.get("summary", ""),
        "citations": data.get("citations", [])[:max_results],
        "source": "gemini-grounded",
    }


async def _serper_search(query: str, max_results: int, api_key: str) -> dict[str, Any]:
    """Google search via Serper.dev API."""
    async with shared_client(timeout=15.0) as client:
        r = await client.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": query, "num": max_results},
        )
        r.raise_for_status()
        data = r.json()
        organic = data.get("organic", [])[:max_results]
        citations = [
            {"title": o.get("title", ""), "url": o.get("link", ""), "snippet": o.get("snippet", "")}
            for o in organic
        ]
        # Build summary from snippets
        summary = " ".join(c["snippet"] for c in citations if c["snippet"])
        return {"query": query, "summary": summary, "citations": citations, "source": "serper"}


async def _tavily_search(query: str, max_results: int, api_key: str) -> dict[str, Any]:
    """Web search via Tavily API."""
    async with shared_client(timeout=15.0) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "include_answer": True,
            },
        )
        r.raise_for_status()
        data = r.json()
        results = data.get("results", [])[:max_results]
        citations = [
            {
                "title": o.get("title", ""),
                "url": o.get("url", ""),
                "snippet": o.get("content", "")[:200],
            }
            for o in results
        ]
        return {
            "query": query,
            "summary": data.get("answer", ""),
            "citations": citations,
            "source": "tavily",
        }


# Tool registry — nodes declare which tools they need
TOOLS = {
    "web_search": web_search,
    "browse_url": browse_url,
    "clarify": clarify,
}


async def dispatch_tool(
    tool_name: str, tool_args: dict[str, Any], *, model_call: ModelCall | None = None
) -> Any:
    """Dispatch supported tools, with model admission supplied by the caller."""
    try:
        if tool_name == "web_search":
            function: Callable[..., Awaitable[Any]] = web_search
            arguments: tuple[Any, ...] = (
                str(tool_args.get("query", "")),
                int(tool_args.get("max_results", 5) or 5),
            )
        elif tool_name == "browse_url":
            function = browse_url
            arguments = (
                str(tool_args.get("url", "")),
                str(tool_args.get("task", "Extract key facts and quotes")),
            )
        elif tool_name == "clarify":
            function = clarify
            arguments = (
                list(tool_args.get("questions", []) or []),
                dict(tool_args.get("context", {}) or {}),
            )
        else:
            return f"Tool '{tool_name}' not available"
    except (TypeError, ValueError) as exc:
        return f"Error: bad arguments for tool '{tool_name}': {exc}"
    # Only argument coercion is recoverable here. A ValueError from malformed
    # provider JSON after dispatch may have left the Invocation UNKNOWN; it
    # must stop the strategy, not invite another model effect under a new key.
    if tool_name in {"clarify", "web_search"}:
        return await cast(Callable[..., Awaitable[Any]], function)(
            *arguments, model_call=model_call
        )
    return await function(*arguments)


def admitted_tool_executor(calls: AdmittedModelCalls) -> ToolCallExecutor:
    """Bind boot Agent tools to the existing execution and effect authorities.

    Agent/delegation/response-round/ToolCall identity names the logical effect.
    It supplies no actor, scope, Binding or credential. The admission adapter
    rereads persisted records and re-resolves the operator Binding every time.
    """

    async def execute(
        call: ToolCall, agent_name: str, delegation_depth: int, tool_round: int
    ) -> Any:
        async def model_call(request: ModelChatRequest) -> str:
            from maistro.runs.store import RunIntegrityError

            if not isinstance(call.id, str) or not call.id.strip():
                raise RunIntegrityError("model-backed Agent tools require the existing ToolCall id")
            if not agent_name.strip():
                raise RunIntegrityError(
                    "model-backed Agent tools require the existing Agent identity"
                )
            scope = json.dumps(
                [agent_name, delegation_depth, tool_round, call.id, call.name],
                separators=(",", ":"),
            )
            result = await calls.complete(
                request=request, effect_key=f"agent-tool:{scope}", timeout_s=30.0
            )
            choices = result.body.get("choices")
            message = (
                choices[0].get("message")
                if isinstance(choices, list) and choices and isinstance(choices[0], dict)
                else None
            )
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, str):
                raise RuntimeError("Agent tool model returned no text content")
            return content

        return await dispatch_tool(call.name, call.arguments, model_call=model_call)

    return ToolCallExecutor(execute)
