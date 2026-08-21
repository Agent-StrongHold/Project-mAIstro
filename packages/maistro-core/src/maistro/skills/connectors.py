"""Marketplace search connectors for ClawHub, Claude Code Plugins, and GitAgent.

Each connector returns SkillMetadata (or dicts for agents) from external
marketplaces. A registry that cannot be reached raises
``MarketplaceUnavailableError`` — connectors never substitute fabricated
results (SPEC-204 §1: the old demo fallback served privileged-looking fake
skills on any HTTP hiccup).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

from maistro.types.errors import AgentError
from maistro.types.skill import SkillMetadata

logger = logging.getLogger("maistro.skills.connectors")


class MarketplaceUnavailableError(AgentError):
    """A marketplace registry could not be reached or answered unusably."""

    code: str = "MARKETPLACE_UNAVAILABLE"


def _normalize(text: str) -> str:
    return text.lower().replace("-", " ").replace("_", " ")


def _matches(query: str, *fields: str) -> bool:
    terms = _normalize(query).split()
    if not terms:
        return True
    combined = " ".join(_normalize(f) for f in fields)
    return all(t in combined for t in terms)


_T = TypeVar("_T")


def _parse_items(raw: Any, build: Callable[[dict[str, Any]], _T], source: str) -> list[_T]:
    """Validate a registry result container and build typed items.

    ``raw`` must be a list (``{"items": null}``, scalars, etc. are unusable);
    non-dict entries are skipped; any schema failure while building is
    translated into the typed outage error so callers never see a raw
    AttributeError/TypeError from a malformed 200 response.
    """
    if not isinstance(raw, list):
        raise MarketplaceUnavailableError(f"{source} returned an unusable payload")
    try:
        return [build(item) for item in raw if isinstance(item, dict)]
    except Exception as exc:
        raise MarketplaceUnavailableError(f"{source} returned an unusable payload") from exc


def _clawhub_skill(s: dict[str, Any]) -> SkillMetadata:
    return SkillMetadata(
        name=s.get("name", ""),
        description=s.get("description", ""),
        source_url=s.get("url", s.get("source_url", "")),
        author=s.get("author", ""),
        source_type="clawhub",
        tags=tuple(s.get("tags", [])),
        download_count=s.get("downloads", s.get("download_count", 0)),
    )


def _claude_plugin_skill(p: dict[str, Any]) -> SkillMetadata:
    return SkillMetadata(
        name=p.get("name", ""),
        description=p.get("description", ""),
        source_url=p.get("homepage", ""),
        author=p.get("author", {}).get("name", "")
        if isinstance(p.get("author"), dict)
        else str(p.get("author", "")),
        source_type="claude_plugins",
        tags=tuple(p.get("tags", p.get("keywords", []))),
    )


def _gitagent_repo(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": r.get("name", ""),
        "description": r.get("description", ""),
        "repo_url": r.get("html_url", ""),
        "author": r.get("owner", {}).get("login", ""),
        "stars": r.get("stargazers_count", 0),
        "source_type": "gitagent",
    }


_claude_cache: list[SkillMetadata] = []
_claude_cache_ts: float = 0.0
_CLAUDE_CACHE_TTL = 300.0


async def search_clawhub(
    query: str = "",
    page: int = 1,
    per_page: int = 20,
    http_client: httpx.AsyncClient | None = None,
) -> list[SkillMetadata]:
    """Search ClawHub public skill registry.

    Raises ``MarketplaceUnavailableError`` when no HTTP client is configured
    or the registry cannot be reached. A genuine empty result set returns [].
    """
    if http_client is None:
        raise MarketplaceUnavailableError("ClawHub search requires an HTTP client")

    try:
        resp = await http_client.get(
            "https://clawhub.ai/api/v1/skills",
            params={"q": query, "page": page, "per_page": per_page},
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning("ClawHub registry unreachable: %s", exc)
        raise MarketplaceUnavailableError("ClawHub registry unreachable") from exc

    if resp.status_code != 200:
        raise MarketplaceUnavailableError(f"ClawHub registry returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception as exc:
        raise MarketplaceUnavailableError("ClawHub registry returned invalid JSON") from exc

    if isinstance(data, list):
        results: Any = data
    elif isinstance(data, dict):
        results = data.get("items", data.get("results", data.get("skills", [])))
    else:
        results = None
    return _parse_items(results, _clawhub_skill, "ClawHub registry")[:per_page]


async def _fetch_claude_plugin_index(
    http_client: httpx.AsyncClient | None,
) -> list[SkillMetadata]:
    """Fetch and parse the official plugin marketplace index, or raise."""
    if http_client is None:
        raise MarketplaceUnavailableError("Claude plugin search requires an HTTP client")

    try:
        resp = await http_client.get(
            "https://raw.githubusercontent.com/anthropics/claude-plugins-official/main/.claude-plugin/marketplace.json",
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning("Claude plugin marketplace unreachable: %s", exc)
        raise MarketplaceUnavailableError("Claude plugin marketplace unreachable") from exc

    if resp.status_code != 200:
        raise MarketplaceUnavailableError(
            f"Claude plugin marketplace returned HTTP {resp.status_code}"
        )

    try:
        data = resp.json()
    except Exception as exc:
        raise MarketplaceUnavailableError(
            "Claude plugin marketplace returned invalid JSON"
        ) from exc

    plugins = data.get("plugins", []) if isinstance(data, dict) else None
    return _parse_items(plugins, _claude_plugin_skill, "Claude plugin marketplace")


async def search_claude_plugins(
    query: str = "",
    http_client: httpx.AsyncClient | None = None,
) -> list[SkillMetadata]:
    """Search Claude Code official plugin marketplace.

    Serves from a short-lived cache when fresh; otherwise fetches the
    marketplace index. Raises ``MarketplaceUnavailableError`` when the index
    cannot be fetched and no fresh cache exists.
    """
    global _claude_cache, _claude_cache_ts

    now = time.monotonic()
    # _claude_cache_ts marks initialization — an empty index is a valid,
    # cacheable answer, so the list itself must not gate the TTL check.
    if not (_claude_cache_ts > 0.0 and (now - _claude_cache_ts) < _CLAUDE_CACHE_TTL):
        _claude_cache = await _fetch_claude_plugin_index(http_client)
        _claude_cache_ts = now

    items = _claude_cache
    if query:
        items = [s for s in items if _matches(query, s.name, s.description, *s.tags)]
    return items


async def search_gitagent_repos(
    query: str = "",
    http_client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Search GitAgent repositories via the GitHub search API.

    An empty query returns [] (GitHub repo search needs a query). Raises
    ``MarketplaceUnavailableError`` when no HTTP client is configured or the
    API cannot be reached.
    """
    if not query:
        return []
    if http_client is None:
        raise MarketplaceUnavailableError("GitAgent search requires an HTTP client")

    try:
        resp = await http_client.get(
            "https://api.github.com/search/repositories",
            params={"q": f"{query} topic:gitagent", "sort": "stars", "per_page": 10},
            timeout=5.0,
        )
    except Exception as exc:
        logger.warning("GitHub search API unreachable: %s", exc)
        raise MarketplaceUnavailableError("GitHub search API unreachable") from exc

    if resp.status_code != 200:
        raise MarketplaceUnavailableError(f"GitHub search API returned HTTP {resp.status_code}")

    try:
        data = resp.json()
    except Exception as exc:
        raise MarketplaceUnavailableError("GitHub search API returned invalid JSON") from exc

    repos = data.get("items", []) if isinstance(data, dict) else None
    return _parse_items(repos, _gitagent_repo, "GitHub search API")
