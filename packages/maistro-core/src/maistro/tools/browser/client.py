"""BrowserClient — drives Chromium via browser-use with gemini-3.1-flash-lite.

Concrete v0 surface:
  - `search_web(query, max_results=3) -> SearchResult` — open google.com,
    search, read top N organic results, return synthesized summary +
    citations. Falls back to duckduckgo.com/html on CAPTCHA.
  - `browse(url, task) -> BrowseResult` — open a URL with an LLM-driven
    objective; return text + duration.
  - `aclose()` — tear down Playwright context cleanly.

LLM client: browser-use's vision-driven Agent runs against the MAISTRO
gateway in OpenAI-compatible mode (LiteLLM is OpenAI-compatible). The
model is gemini-3.1-flash-lite — vision-capable, cheap, fast. PM agents
running on claude-sonnet-4-6 delegate WEB work to this lighter LLM;
they don't pay sonnet rates per browser step.

Network boundary (#855): every session this client runs is a Playwright
context with `BrowserNetworkGuard` attached *before* browser-use ever sees
it, so the canonical outbound policy governs every navigation — the ones
the task names, the ones the model invents mid-run, redirect hops, and
subresources. `browse()` still checks its explicit starting URL first, but
that is an early, caller-friendly refusal, not the enforcement boundary;
the boundary is the route handler. A browser-use build that cannot be
handed a guarded context is refused outright (fail closed — there is no
"run it unguarded" fallback).

Errors wrap in BrowserToolError. Caller (pm_runner._run_web_research)
catches them and returns source='no_data' rather than fabricate.

Import discipline: this module is the ONLY place that imports
`browser_use` / `playwright`. Pinning + library-drift containment.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import time
from dataclasses import dataclass
from typing import Any

from maistro.security.ssrf import SSRFBlockedError, avalidate_outbound_url
from maistro.tools.browser.guard import BrowserNetEvent, BrowserNetworkGuard
from maistro.tools.browser.types import BrowseResult, Citation, SearchResult


class BrowserToolError(RuntimeError):
    """Raised when browser-use / Playwright fails. Caller should return
    source='no_data' rather than guess at content."""


def _resolve_llm_base_url() -> str:
    # Same env-var fallback chain as pm_llm_call (see llm-gateway notes).
    return (
        os.environ.get("LITELLM_URL")
        or os.environ.get("LITELLM_BASE_URL")
        or os.environ.get("LITELLM_PROXY_URL")
        or ""
    ).rstrip("/")


def _resolve_llm_api_key() -> str:
    return os.environ.get("LITELLM_MASTER_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""


def _resolve_browser_model() -> str:
    # gemini-3.1-flash-lite is the v0 default (user-locked). Vision-
    # capable, fast, cheap. Overrideable via BROWSER_USE_MODEL for
    # operators who want sonnet-quality reasoning at higher cost.
    return os.environ.get("BROWSER_USE_MODEL") or "gemini-3.1-flash-lite"


def _resolve_browser_allowed_origins() -> tuple[str, ...]:
    """Host-owned extra origins the *browser* may reach (`#855`).

    Comma-separated, read from the environment an operator controls. These
    layer onto the shared outbound policy for browser traffic only — they
    do not widen what ordinary HTTP effects may do, and nothing a page or
    a model returns can add to them.
    """
    raw = os.environ.get("BROWSER_USE_ALLOWED_ORIGINS", "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _is_truthy(val: str | None) -> bool:
    return (val or "").lower() in {"1", "true", "yes", "on"}


_SEARCH_INSTRUCTIONS = """
You are operating a real browser. Goal: gather background on the topic below.
Steps:
 1. Navigate to https://www.google.com.
 2. Enter the query in the search box and submit.
 3. Read the top {max_results} ORGANIC results (skip "Sponsored", "Ads",
    "AI Overview", and "People also ask" — those are not citations).
 4. For each result, extract: title (str), url (str), snippet (str — the
    1-2 line preview Google shows below the result).
 5. After collecting citations, write a 3-sentence factual SUMMARY that
    synthesizes what these sources say. Do not invent claims; if the
    citations disagree, say so.
 6. If Google blocks you with CAPTCHA or a "Before you continue" prompt,
    try https://duckduckgo.com/html instead (no JS, no CAPTCHA there).
 7. If both engines block, return summary="search engines unreachable"
    and citations=[].

Never fabricate URLs. Only return URLs you saw rendered on the page.

Topic: {query}
"""


@dataclass(frozen=True)
class _GuardedSession:
    """A governed Chromium handed to browser-use, plus how to undo it.

    `agent_kwargs` is splatted into the Agent constructor — the one kwarg
    the installed browser-use version uses to accept an externally-owned
    browser. `teardown` closes the Playwright objects this client owns.
    """

    agent_kwargs: dict[str, Any]
    guard: BrowserNetworkGuard
    context: Any
    teardown: Any  # Callable[[], Awaitable[None]]


class _GuardedPlaywrightBrowser:
    """A Playwright `Browser` whose every context is route-guarded.

    For browser-use builds that accept a Playwright *browser* rather than a
    context (`BrowserSession(playwright_browser=...)`): whatever context
    they create from it is intercepted on creation and given the outbound
    policy, so the guard holds even though browser-use owns context
    creation. Attribute access forwards to the wrapped browser.
    """

    def __init__(self, inner: Any, guard: BrowserNetworkGuard) -> None:
        self._inner = inner
        self._guard = guard

    async def new_context(self, *args: Any, **kwargs: Any) -> Any:
        context = await self._inner.new_context(*args, **kwargs)
        await self._guard.attach(context)
        return context

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _ctor_param_names(cls: Any) -> set[str]:
    """Named parameters of a class's constructor.

    `**kwargs` is deliberately *not* treated as accepting anything: a
    library that swallows unknown kwargs into a profile would silently
    ignore the context we handed it and build its own — an unguarded
    browser wearing a guarded kwarg. Only an explicitly named parameter
    proves the build knows what to do with the object.
    """
    named = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    try:
        params = inspect.signature(cls).parameters.values()
    except (TypeError, ValueError):
        return set()
    return {p.name for p in params if p.kind in named}


class BrowserClient:
    """v0 in-process Playwright + browser-use wrapper.

    Designed for single-call use: instantiate, call search_web/browse,
    aclose. v1 may add a per-process pooled Chromium for sub-second
    repeat calls.
    """

    def __init__(
        self,
        *,
        llm_model: str | None = None,
        headless: bool | None = None,
        timeout_s: int = 90,
        max_steps: int | None = None,
    ) -> None:
        self.llm_model = llm_model or _resolve_browser_model()
        self.headless = (
            headless
            if headless is not None
            else _is_truthy(os.environ.get("BROWSER_USE_HEADLESS", "true"))
        )
        self.timeout_s = float(os.environ.get("BROWSER_USE_TIMEOUT_S", timeout_s))
        self.max_steps = int(
            max_steps if max_steps is not None else os.environ.get("BROWSER_USE_MAX_STEPS", "15")
        )
        # Lazy imports — keep `browser_use` / `playwright` scoped here so
        # importing maistro.tools.browser doesn't fail in environments
        # where the Chromium runtime isn't installed.
        self._browser_use: Any = None
        # The guard of the most recent run, for audit access after the fact.
        self._last_guard: BrowserNetworkGuard | None = None

    def _import_browser_use(self) -> Any:
        if self._browser_use is not None:
            return self._browser_use
        try:
            import browser_use  # type: ignore
        except ImportError as exc:
            raise BrowserToolError(
                "browser-use not installed in this environment. "
                "maistro-engine image bakes it in via Dockerfile; "
                "local dev can `pip install browser-use playwright && "
                "playwright install chromium`."
            ) from exc
        self._browser_use = browser_use
        return browser_use

    def _build_llm(self) -> Any:
        """Construct the browser-use LLM client pointed at the LLM gateway."""
        base_url = _resolve_llm_base_url()
        api_key = _resolve_llm_api_key()
        if not base_url or not api_key:
            raise BrowserToolError(
                "LLM gateway not configured for browser-use: LITELLM_URL "
                "(or LITELLM_PROXY_URL) + LITELLM_MASTER_KEY required."
            )
        bu = self._import_browser_use()
        # browser-use supports `ChatOpenAI`-style configuration. Different
        # versions name this slightly differently; try both common APIs.
        ChatOpenAI = getattr(bu, "ChatOpenAI", None) or getattr(
            getattr(bu, "llm", object()), "ChatOpenAI", None
        )
        if ChatOpenAI is None:
            # Fallback: use the openai sdk directly via browser-use's
            # generic OpenAI-compatible wrapper.
            from openai import AsyncOpenAI  # type: ignore[import-not-found]  # optional extra

            return AsyncOpenAI(base_url=base_url, api_key=api_key)
        return ChatOpenAI(
            model=self.llm_model,
            base_url=base_url,
            api_key=api_key,
            temperature=0.1,
        )

    # --- the governed network boundary (#855) -------------------------------

    async def _start_guarded_session(self, bu: Any) -> _GuardedSession:
        """Launch Chromium, guard its network, wrap it for browser-use.

        The guard is attached before browser-use receives anything, so
        there is no window in which an unguarded context exists. Every
        failure path tears the Playwright objects back down — a half-built
        session must not leak a live browser.
        """
        pw, browser, context = await self._launch_playwright_context()
        guard = BrowserNetworkGuard(extra_origins=_resolve_browser_allowed_origins())
        try:
            await guard.attach(context)
            name, value = self._wrap_for_browser_use(bu, browser, context, guard)
        except BaseException:
            await self._teardown_playwright(pw, browser, context)
            raise

        async def teardown() -> None:
            await self._teardown_playwright(pw, browser, context)

        return _GuardedSession(
            agent_kwargs={name: value}, guard=guard, context=context, teardown=teardown
        )

    async def _launch_playwright_context(self) -> tuple[Any, Any, Any]:
        """`(playwright, browser, context)` with the guard's prerequisites.

        Service workers are blocked because Playwright's route layer does
        not see fetches a service worker makes on a page's behalf — an
        unregistered worker cannot stand in for a governed request.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserToolError(
                "playwright not installed in this environment. The "
                "maistro-engine image bakes it in via Dockerfile; local "
                "dev can `pip install playwright && playwright install "
                "chromium`. A browser session cannot run without the "
                "network guard, so there is no fallback."
            ) from exc
        pw = await async_playwright().start()
        browser: Any = None
        try:
            browser = await pw.chromium.launch(headless=self.headless)
            context = await browser.new_context(service_workers="block")
        except BaseException:
            if browser is not None:
                await _quiet(browser.close)
            await _quiet(pw.stop)
            raise
        return pw, browser, context

    def _wrap_for_browser_use(
        self, bu: Any, browser: Any, context: Any, guard: BrowserNetworkGuard
    ) -> tuple[str, Any]:
        """`(kwarg_name, browser_object)` for the installed browser-use.

        browser-use has changed how an externally-owned browser is handed
        to an Agent across versions: `Agent(browser=Browser(...))` in the
        0.1-0.2 line, `Agent(browser_session=BrowserSession(...))` after.
        Each strategy is used only when the constructor *names* the
        parameter (see `_ctor_param_names` for why `**kwargs` proves
        nothing), and when no strategy fits, the session is refused —
        running an ungovernable browser is not an option this client
        offers (#855's stop condition: the transport must deny).
        """
        Agent = getattr(bu, "Agent", None)
        agent_params = _ctor_param_names(Agent) if Agent is not None else set()

        Browser = getattr(bu, "Browser", None)
        if "browser" in agent_params and Browser is not None:
            browser_params = _ctor_param_names(Browser)
            if "playwright_browser_context" in browser_params:
                return "browser", Browser(playwright_browser_context=context)

        BrowserSession = getattr(bu, "BrowserSession", None)
        if "browser_session" in agent_params and BrowserSession is not None:
            session_params = _ctor_param_names(BrowserSession)
            if "playwright_browser_context" in session_params:
                return "browser_session", BrowserSession(playwright_browser_context=context)
            if "playwright_browser" in session_params:
                return (
                    "browser_session",
                    BrowserSession(playwright_browser=_GuardedPlaywrightBrowser(browser, guard)),
                )

        raise BrowserToolError(
            "browser-use version cannot be governed: no supported way to hand "
            "its Agent a policy-guarded Playwright browser (tried "
            "Agent(browser=Browser(playwright_browser_context=...)) and "
            "Agent(browser_session=BrowserSession(...))). Refusing to run an "
            "unguarded browser session — pin a browser-use version this "
            "client can govern."
        )

    @staticmethod
    async def _teardown_playwright(pw: Any, browser: Any, context: Any) -> None:
        """Close everything `_launch_playwright_context` opened, best-effort
        and in reverse order. Teardown must not raise past the caller's own
        result or error."""
        await _quiet(context.close)
        await _quiet(browser.close)
        await _quiet(pw.stop)

    # --- the two public operations -------------------------------------------

    async def _run_agent(self, task: str) -> Any:
        """Run one browser-use Agent on a guarded session.

        Shared by `search_web` and `browse` because the boundary must hold
        for both: an autonomous search agent inventing `127.0.0.1` and a
        browse agent following a redirect there are governed by the same
        attached route handler, not by how the task text was written.
        """
        bu = self._import_browser_use()
        Agent = getattr(bu, "Agent", None)
        if Agent is None:
            raise BrowserToolError("browser-use.Agent class not available")
        llm = self._build_llm()
        session = await self._start_guarded_session(bu)
        self._last_guard = session.guard
        try:
            agent = Agent(task=task, llm=llm, max_steps=self.max_steps, **session.agent_kwargs)
            return await asyncio.wait_for(agent.run(), timeout=self.timeout_s)
        finally:
            await session.teardown()

    def last_net_events(self) -> tuple[BrowserNetEvent, ...]:
        """The network decisions of the most recent run, oldest first.

        The auditable evidence `#855` asks the provider to emit: allowed
        and denied, origins only, no query contents.
        """
        if self._last_guard is None:
            return ()
        return tuple(self._last_guard.events)

    async def search_web(self, query: str, *, max_results: int = 3) -> SearchResult:
        """Drive a real Chromium session through Google → synthesize results."""
        task = _SEARCH_INSTRUCTIONS.format(query=query, max_results=max_results)
        start = time.monotonic()
        try:
            run_result = await self._run_agent(task)
        except TimeoutError as exc:
            raise BrowserToolError(
                f"browser-use search_web timed out after {self.timeout_s}s"
            ) from exc
        except BrowserToolError:
            raise
        except Exception as exc:
            raise BrowserToolError(f"browser-use search_web failed: {exc}") from exc
        duration_ms = int((time.monotonic() - start) * 1000)
        return self._parse_search_output(query, run_result, duration_ms)

    async def browse(self, url: str, task: str) -> BrowseResult:
        """Open `url` with an LLM-driven objective; return collected text."""
        start = time.monotonic()
        full_task = (
            f"Navigate to {url}. Then: {task}. Return a 2-3 paragraph factual "
            "summary of what you read. Do not invent details — quote where "
            "possible."
        )
        # An early, caller-friendly refusal for the URL the caller actually
        # named. Defense in depth only: the enforced boundary is the route
        # guard on the session below, which sees every later destination
        # this check cannot (redirects, model-chosen navigations,
        # subresources).
        try:
            await avalidate_outbound_url(url)
        except SSRFBlockedError as exc:
            raise BrowserToolError(f"browse blocked by SSRF guard: {exc}") from exc
        try:
            run_result = await self._run_agent(full_task)
        except BrowserToolError:
            raise
        except Exception as exc:
            raise BrowserToolError(f"browser-use browse failed: {exc}") from exc
        duration_ms = int((time.monotonic() - start) * 1000)
        text = self._extract_text(run_result)
        return BrowseResult(
            url=url,
            title=self._extract_title(run_result) or url,
            text=text,
            duration_ms=duration_ms,
        )

    async def aclose(self) -> None:
        # Each run tears its own Playwright objects down in `_run_agent`'s
        # finally; placeholder for v1 connection-pool teardown.
        return None

    def _parse_search_output(self, query: str, run_result: Any, duration_ms: int) -> SearchResult:
        """Coerce browser-use's RunHistory shape into SearchResult. Versions
        differ: history.final_result, result.output, .output_message all
        seen. Defensive across all of them."""
        text = self._extract_text(run_result)
        # Try JSON-shape extraction first.
        import json as _json
        import re

        cleaned = re.sub(r"```(?:json)?\s*", "", text)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned).strip()
        parsed: dict[str, Any] | None = None
        try:
            parsed = _json.loads(cleaned)
        except (ValueError, TypeError):
            parsed = None

        citations: tuple[Citation, ...] = ()
        summary = ""
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary") or "")
            raw_cites = parsed.get("citations") or parsed.get("sources") or []
            if isinstance(raw_cites, list):
                citations = tuple(
                    Citation(
                        title=str(c.get("title", "")),
                        url=str(c.get("url", "")),
                        snippet=str(c.get("snippet", "")),
                    )
                    for c in raw_cites
                    if isinstance(c, dict) and c.get("url")
                )
        if not summary:
            # Fallback: use the raw text up to 600 chars as the summary,
            # with empty citations — the LLM didn't return parseable JSON.
            summary = text[:600] if text else f"No content returned for query: {query}"
        source = "browser-use"
        if "duckduckgo" in text.lower():
            source = "duckduckgo-fallback"
        if "unreachable" in summary.lower():
            source = "error"
        return SearchResult(
            query=query,
            summary=summary,
            citations=citations,
            duration_ms=duration_ms,
            source=source,
        )

    @staticmethod
    def _extract_text(run_result: Any) -> str:
        # browser-use versions: .final_result | .output | str(run_result).
        for attr in ("final_result", "output", "last_message", "result"):
            v = getattr(run_result, attr, None)
            if v:
                return str(v)
        return str(run_result) if run_result is not None else ""

    @staticmethod
    def _extract_title(run_result: Any) -> str | None:
        v = getattr(run_result, "title", None)
        return str(v) if v else None


async def _quiet(coro_factory: Any) -> None:
    """Await a teardown callable, swallowing (and debug-logging) its failure:
    a context that is already closed must not turn cleanup into an error the
    caller's real result then has to survive."""
    with contextlib.suppress(Exception):
        await coro_factory()


__all__ = ["BrowserClient", "BrowserToolError"]
