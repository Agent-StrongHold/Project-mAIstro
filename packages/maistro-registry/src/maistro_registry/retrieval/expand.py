"""LLM query expansion over an OpenAI-compatible endpoint.

Issue #26 lists "LLM query expansion" as one input to corpus-aware
retrieval — but an expansion call must never make retrieval *depend* on a
service being up. The shape is therefore:

- a `QueryExpander` protocol (one method: query -> candidate terms),
- `NoExpansion`, the deterministic default that adds nothing, and
- `OpenAICompatExpander`, which asks an OpenAI-compatible chat endpoint
  (LiteLLM proxy, vLLM, OpenAI itself) for a JSON array of search terms.

Two failure disciplines, both deliberate:

- The expander *raises* `ExpansionError` on any transport, auth, or
  parsing failure; it does not return a best guess. A silently-empty
  expansion is indistinguishable from "the model found nothing" and
  would hide an outage.
- The *searcher* (search.RetrievalSearcher) catches `ExpansionError`,
  records that expansion was skipped, and proceeds lexical-only. The
  CLI prints the skip to stderr. Degradation is visible and truthful,
  never fabricated.

Expansion output is *candidate* terms: the searcher still filters every
expansion term through corpus statistics (`terms.CorpusStats`), so a
model that confidently suggests terms this corpus has never used gains
nothing — the corpus, not the LLM, has the last word.

HTTP goes through `maistro.http.sync_client`, so expansion traffic rides
the same outbound policy as every other client this process builds
(`linker.py` set this precedent for the GitHub resolver).
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol

import httpx

from maistro.http import sync_client

# Module-level so tests can monkeypatch it, exactly like linker.py.
_EXPANSION_TIMEOUT_SECONDS = 15.0
_MAX_EXPANSION_TERMS = 8

_SYSTEM_PROMPT = (
    "You expand search queries against a software architecture corpus of "
    "ADR (architecture decision records), specs, and known-gap documents. "
    "Given a query, return a JSON array of 3-8 alternative search terms or "
    "short phrases likely to appear in the relevant documents: synonyms, "
    "related registry ids, component names. Return ONLY the JSON array — "
    "no prose, no code fences."
)


class QueryExpander(Protocol):
    """Anything that can propose additional search terms for a query."""

    def expand(self, query: str) -> list[str]:
        """Propose candidate terms; raise ExpansionError on failure."""
        ...


class ExpansionError(RuntimeError):
    """An expansion call failed (transport, auth, or unparseable output)."""


class NoExpansion:
    """The default expander: contributes nothing, never fails.

    Lexical retrieval must be runnable with zero services up — the
    baseline is what quality is measured *against*.
    """

    def expand(self, query: str) -> list[str]:
        return []


class OpenAICompatExpander:
    """Query expansion against an OpenAI-compatible `/chat/completions`.

    `base_url` is the API root (e.g. `http://localhost:4000` for a local
    LiteLLM proxy); `api_key` defaults to the `MAISTRO_EXPAND_API_KEY`
    environment variable, matching how the compose stack already hands
    out proxy keys.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = _EXPANSION_TIMEOUT_SECONDS,
        max_terms: int = _MAX_EXPANSION_TERMS,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key if api_key is not None else os.environ.get("MAISTRO_EXPAND_API_KEY")
        self._timeout = timeout
        self._max_terms = max_terms

    @property
    def completions_url(self) -> str:
        return f"{self._base_url}/chat/completions"

    def expand(self, query: str) -> list[str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            "temperature": 0,
            "max_tokens": 200,
        }
        try:
            with sync_client(timeout=self._timeout) as client:
                response = client.post(self.completions_url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ExpansionError(f"expansion request failed: {exc}") from exc
        return self._parse_terms(body)

    def _parse_terms(self, body: dict[str, Any]) -> list[str]:
        """Extract the term list from a chat-completions response.

        Accepts a bare JSON array or a fenced/embedded one (models wrap
        arrays in ```json fences often enough that tolerating it here is
        cheaper than failing callers who then retry manually). Anything
        else is an ExpansionError — see the module docstring on why this
        never degrades silently.
        """
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExpansionError(f"unexpected completion shape: {body!r}") from exc
        if not isinstance(content, str):
            raise ExpansionError("completion content is not a string")
        terms = _extract_json_array(content)
        cleaned: list[str] = []
        for term in terms:
            if not isinstance(term, str):
                continue
            stripped = term.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned[: self._max_terms]


def _extract_json_array(content: str) -> list[Any]:
    """Pull the first JSON array out of model output, fences included."""
    text = content.strip()
    if "```" in text:
        for chunk in text.split("```"):
            chunk = chunk.removeprefix("json").strip()
            if chunk.startswith("["):
                text = chunk
                break
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ExpansionError(f"no JSON array in expansion output: {content[:200]!r}")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ExpansionError(f"invalid JSON in expansion output: {exc}") from exc
    if not isinstance(parsed, list):
        raise ExpansionError("expansion output is not a JSON array")
    return parsed
