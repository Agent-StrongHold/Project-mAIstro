"""Coverage for skills/connectors.py.

The demo fallback was removed (SPEC-204 §1): a registry outage raises
MarketplaceUnavailableError instead of serving fabricated skills. These tests
pin both the success paths and the fail-closed behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.skills import connectors
from maistro.skills.connectors import (
    MarketplaceUnavailableError,
    _matches,
    _normalize,
    search_claude_plugins,
    search_clawhub,
    search_gitagent_repos,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeHttpClient:
    def __init__(
        self, response: _FakeResponse | None = None, error: Exception | None = None
    ) -> None:
        self._response = response
        self._error = error
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(
        self, url: str, params: dict[str, Any] | None = None, timeout: float = 5.0
    ) -> _FakeResponse:
        self.calls.append((url, params or {}))
        if self._error:
            raise self._error
        assert self._response is not None
        return self._response


@pytest.fixture(autouse=True)
def reset_claude_cache() -> None:
    connectors._claude_cache = []
    connectors._claude_cache_ts = 0.0


def test_normalize_lowercases_and_replaces_separators() -> None:
    assert _normalize("Web-Search_Tool") == "web search tool"


def test_matches_returns_true_for_empty_query() -> None:
    assert _matches("", "anything") is True


def test_matches_returns_true_when_all_terms_present() -> None:
    assert _matches("web search", "Web-Search", "desc") is True


def test_matches_returns_false_when_a_term_missing() -> None:
    assert _matches("web search", "Web-Search tool", "unrelated") is True
    assert _matches("github pr", "web search", "desc") is False


# ── ClawHub ──────────────────────────────────────────────────────


async def test_search_clawhub_raises_without_client() -> None:
    with pytest.raises(MarketplaceUnavailableError):
        await search_clawhub()


async def test_search_clawhub_uses_client_list_response() -> None:
    client = _FakeHttpClient(
        response=_FakeResponse(
            200,
            [
                {
                    "name": "x",
                    "description": "y",
                    "url": "u",
                    "author": "a",
                    "tags": ["t"],
                    "downloads": 5,
                }
            ],
        )
    )
    results = await search_clawhub(http_client=client)
    assert len(results) == 1
    assert results[0].name == "x"
    assert results[0].source_url == "u"
    assert results[0].download_count == 5
    assert len(client.calls) == 1


async def test_search_clawhub_uses_client_dict_items_response() -> None:
    client = _FakeHttpClient(
        response=_FakeResponse(200, {"items": [{"name": "z", "description": "d"}]})
    )
    results = await search_clawhub(http_client=client)
    assert len(results) == 1
    assert results[0].name == "z"


async def test_search_clawhub_empty_results_are_returned_not_replaced() -> None:
    """A genuine empty result set is [], never substituted fixtures."""
    client = _FakeHttpClient(response=_FakeResponse(200, {"items": []}))
    assert await search_clawhub(http_client=client) == []


async def test_search_clawhub_raises_on_non_200() -> None:
    client = _FakeHttpClient(response=_FakeResponse(404, {}))
    with pytest.raises(MarketplaceUnavailableError):
        await search_clawhub(http_client=client)


async def test_search_clawhub_raises_on_transport_error() -> None:
    client = _FakeHttpClient(error=ConnectionError("registry down"))
    with pytest.raises(MarketplaceUnavailableError):
        await search_clawhub(http_client=client)


async def test_search_clawhub_raises_on_scalar_payload() -> None:
    """A 200 with an unusable shape is the typed error, not AttributeError."""
    client = _FakeHttpClient(response=_FakeResponse(200, "not-a-container"))
    with pytest.raises(MarketplaceUnavailableError):
        await search_clawhub(http_client=client)


async def test_search_clawhub_raises_on_null_items() -> None:
    client = _FakeHttpClient(response=_FakeResponse(200, {"items": None}))
    with pytest.raises(MarketplaceUnavailableError):
        await search_clawhub(http_client=client)


async def test_search_clawhub_raises_on_malformed_entry_schema() -> None:
    """A schema failure inside an entry (scalar tags) is the typed error."""
    client = _FakeHttpClient(response=_FakeResponse(200, {"items": [{"name": "x", "tags": 7}]}))
    with pytest.raises(MarketplaceUnavailableError):
        await search_clawhub(http_client=client)


# ── Claude plugins ───────────────────────────────────────────────


async def test_search_claude_plugins_raises_without_client_or_cache() -> None:
    with pytest.raises(MarketplaceUnavailableError):
        await search_claude_plugins()


async def test_search_claude_plugins_builds_cache_from_client() -> None:
    client = _FakeHttpClient(
        response=_FakeResponse(
            200,
            {
                "plugins": [
                    {
                        "name": "mcp-filesystem",
                        "description": "files",
                        "homepage": "h",
                        "author": {"name": "Anthropic"},
                        "keywords": ["mcp"],
                    }
                ]
            },
        )
    )
    results = await search_claude_plugins(http_client=client)
    assert [s.name for s in results] == ["mcp-filesystem"]
    assert results[0].author == "Anthropic"
    assert connectors._claude_cache


async def test_search_claude_plugins_uses_cache_within_ttl() -> None:
    client = _FakeHttpClient(
        response=_FakeResponse(200, {"plugins": [{"name": "cached", "homepage": "h"}]})
    )
    await search_claude_plugins(http_client=client)
    # Second call must not hit the network — and works with no client at all.
    results = await search_claude_plugins()
    assert [s.name for s in results] == ["cached"]
    assert len(client.calls) == 1


async def test_search_claude_plugins_filters_by_query_and_tags() -> None:
    client = _FakeHttpClient(
        response=_FakeResponse(
            200,
            {
                "plugins": [
                    {"name": "mcp-github", "description": "gh", "keywords": ["mcp"]},
                    {"name": "other", "description": "misc", "keywords": []},
                ]
            },
        )
    )
    results = await search_claude_plugins(query="mcp", http_client=client)
    assert [s.name for s in results] == ["mcp-github"]


async def test_search_claude_plugins_raises_on_non_200() -> None:
    client = _FakeHttpClient(response=_FakeResponse(500, {}))
    with pytest.raises(MarketplaceUnavailableError):
        await search_claude_plugins(http_client=client)


async def test_search_claude_plugins_raises_on_transport_error() -> None:
    client = _FakeHttpClient(error=ConnectionError("index down"))
    with pytest.raises(MarketplaceUnavailableError):
        await search_claude_plugins(http_client=client)


async def test_search_claude_plugins_raises_on_non_dict_payload() -> None:
    client = _FakeHttpClient(response=_FakeResponse(200, ["not", "a", "dict"]))
    with pytest.raises(MarketplaceUnavailableError):
        await search_claude_plugins(http_client=client)


async def test_search_claude_plugins_empty_index_is_cached() -> None:
    """A valid empty index must be served from cache — one fetch, then a
    clientless call returns [] instead of raising (Codex review on #306)."""
    client = _FakeHttpClient(response=_FakeResponse(200, {"plugins": []}))
    assert await search_claude_plugins(http_client=client) == []
    assert await search_claude_plugins() == []
    assert len(client.calls) == 1


# ── GitAgent ─────────────────────────────────────────────────────


async def test_search_gitagent_repos_empty_query_returns_empty() -> None:
    assert await search_gitagent_repos() == []


async def test_search_gitagent_repos_raises_without_client() -> None:
    with pytest.raises(MarketplaceUnavailableError):
        await search_gitagent_repos(query="planner")


async def test_search_gitagent_repos_uses_client_response() -> None:
    client = _FakeHttpClient(
        response=_FakeResponse(
            200,
            {
                "items": [
                    {
                        "name": "agent-kit",
                        "description": "d",
                        "html_url": "u",
                        "owner": {"login": "me"},
                        "stargazers_count": 7,
                    }
                ]
            },
        )
    )
    results = await search_gitagent_repos(query="agent", http_client=client)
    assert results == [
        {
            "name": "agent-kit",
            "description": "d",
            "repo_url": "u",
            "author": "me",
            "stars": 7,
            "source_type": "gitagent",
        }
    ]


async def test_search_gitagent_repos_empty_items_returned_not_replaced() -> None:
    client = _FakeHttpClient(response=_FakeResponse(200, {"items": []}))
    assert await search_gitagent_repos(query="agent", http_client=client) == []


async def test_search_gitagent_repos_raises_on_non_200() -> None:
    client = _FakeHttpClient(response=_FakeResponse(403, {}))
    with pytest.raises(MarketplaceUnavailableError):
        await search_gitagent_repos(query="agent", http_client=client)


async def test_search_gitagent_repos_raises_on_transport_error() -> None:
    client = _FakeHttpClient(error=ConnectionError("api down"))
    with pytest.raises(MarketplaceUnavailableError):
        await search_gitagent_repos(query="agent", http_client=client)


async def test_search_gitagent_repos_raises_on_non_list_items() -> None:
    client = _FakeHttpClient(response=_FakeResponse(200, {"items": "nope"}))
    with pytest.raises(MarketplaceUnavailableError):
        await search_gitagent_repos(query="agent", http_client=client)


async def test_search_gitagent_repos_skips_non_dict_entries() -> None:
    client = _FakeHttpClient(response=_FakeResponse(200, {"items": ["junk", {"name": "ok"}]}))
    results = await search_gitagent_repos(query="agent", http_client=client)
    assert [r["name"] for r in results] == ["ok"]


def test_no_adversarial_fixture_names_ship() -> None:
    """The removed fixtures must not resurface anywhere in the module."""
    import inspect

    src = inspect.getsource(connectors)
    for name in ("code-executor-unlimited", "credential-helper", "admin-override"):
        assert name not in src
