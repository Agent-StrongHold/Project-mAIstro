"""Browser tool — Playwright + browser-use, driven by gemini-3.1-flash-lite
via the LLM gateway. Replaces the v0 `web_search_background` stub.

PAT/key isolation: browser-use's LLM client is configured against the
same LLM gateway as PM agents; the user's virtual key (LITELLM_*)
travels in headers, not env-baked. The Chromium binary is baked into
the maistro-engine image (Dockerfile additions, Day 4) so this tool is
in-process — no sidecar.

Headless by default; pass `headless=False` only in dev. Google CAPTCHAs
from corp egress fall back to duckduckgo.com/html — coded into the
search task prompt rather than a separate code path.
"""

from __future__ import annotations

from maistro.tools.browser.client import (
    BrowserClient,
    BrowserToolError,
)
from maistro.tools.browser.types import (
    BrowseResult,
    Citation,
    SearchResult,
)

__all__ = [
    "BrowseResult",
    "BrowserClient",
    "BrowserToolError",
    "Citation",
    "SearchResult",
]
