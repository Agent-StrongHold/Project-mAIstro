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

Errors wrap in BrowserToolError. Caller (pm_runner._run_web_research)
catches them and returns source='no_data' rather than fabricate.

Import discipline: this module is the ONLY place that imports
`browser_use` / `playwright`. Pinning + library-drift containment.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from maistro.tools.browser.types import BrowseResult, Citation, SearchResult
from maistro.tools.net_guard import SSRFBlockedError, validate_outbound_url


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
    1-2 line preview Google shows below the title).
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

    async def search_web(self, query: str, *, max_results: int = 3) -> SearchResult:
        """Drive a real Chromium session through Google → synthesize results."""
        bu = self._import_browser_use()
        Agent = getattr(bu, "Agent", None)
        if Agent is None:
            raise BrowserToolError("browser-use.Agent class not available")
        llm = self._build_llm()
        task = _SEARCH_INSTRUCTIONS.format(query=query, max_results=max_results)
        start = time.monotonic()
        try:
            agent = Agent(task=task, llm=llm, max_steps=self.max_steps)
            run_result = await asyncio.wait_for(
                agent.run(),
                timeout=self.timeout_s,
            )
        except TimeoutError as exc:
            raise BrowserToolError(
                f"browser-use search_web timed out after {self.timeout_s}s"
            ) from exc
        except Exception as exc:
            raise BrowserToolError(f"browser-use search_web failed: {exc}") from exc
        duration_ms = int((time.monotonic() - start) * 1000)
        return self._parse_search_output(query, run_result, duration_ms)

    async def browse(self, url: str, task: str) -> BrowseResult:
        """Open `url` with an LLM-driven objective; return collected text."""
        bu = self._import_browser_use()
        Agent = getattr(bu, "Agent", None)
        if Agent is None:
            raise BrowserToolError("browser-use.Agent class not available")
        llm = self._build_llm()
        start = time.monotonic()
        full_task = (
            f"Navigate to {url}. Then: {task}. Return a 2-3 paragraph factual "
            "summary of what you read. Do not invent details — quote where "
            "possible."
        )
        try:
            validate_outbound_url(url)
        except SSRFBlockedError as exc:
            raise BrowserToolError(f"browse blocked by SSRF guard: {exc}") from exc
        try:
            agent = Agent(task=full_task, llm=llm, max_steps=self.max_steps)
            run_result = await asyncio.wait_for(
                agent.run(),
                timeout=self.timeout_s,
            )
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
        # browser-use Agent context closes itself when its task ends;
        # placeholder for v1 connection-pool teardown.
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


__all__ = ["BrowserClient", "BrowserToolError"]
