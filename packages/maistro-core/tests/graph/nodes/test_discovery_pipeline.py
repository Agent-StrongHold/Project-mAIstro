"""The bounded discovery pipeline (#1051): governed fetch, scout, curator.

Each acceptance claim is exercised against the real governed egress (an
in-memory effect context with the canonical Binding/Invocation/credential
authorities, mirroring `test_pm_polling_nodes.py`), a fake HTTP transport,
and the bare/discovery-context authority split — so the tests prove the
nodes behave through the seams production wires, not around them.
"""

from __future__ import annotations

import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.discovery_source import invoke_discovery_source
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.capabilities.providers.discovery_source import (
    DiscoverySourceRequest,
    execute_discovery_source,
    resolve_discovery_source_provider,
)
from maistro.graph.dag_validator import validate_dag
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.discovery_context import (
    DiscoveryBudgetExhausted,
    DiscoveryCycleContext,
    default_discovery_context,
)
from maistro.graph.nodes.discovery_curate import DiscoveryCurateNode
from maistro.graph.nodes.discovery_scout import DiscoveryScoutNode, fingerprint_for
from maistro.graph.nodes.discovery_source_fetch import DiscoverySourceFetchNode
from maistro.graph.seeds import proactive_discovery_seed

_WS = "ws-1"
_PROJECT = "project-1"
_SOURCE_URL = "https://feeds.example.com/rss"


def _ctx(node_id: str = "n1") -> NodeContext:
    return NodeContext(
        run_id="run-1",
        dag_id="graph-1",
        node_id=node_id,
        node_run_id=f"nr-{node_id}",
        attempt_id="attempt-1",
        workspace_id=_WS,
        project_id=_PROJECT,
    )


class _Cycle:
    """A discovery context authority stub: fixed context, recorded cycle keys."""

    def __init__(self, context: DiscoveryCycleContext) -> None:
        self.context = context
        self.asked: list[str] = []

    async def context_for(
        self, workspace_id: str, project_id: str, user_id: str, cycle_key: str = ""
    ) -> DiscoveryCycleContext:
        self.asked.append(cycle_key)
        return self.context


def _no_context() -> _Cycle:
    return _Cycle(DiscoveryCycleContext())


async def _effects_with_source(
    *, config: dict[str, object] | None = None
) -> CapabilityEffectContext:
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            binding_id="dsrc-1",
            workspace_id=_WS,
            project_id=_PROJECT,
            node_id="n1",
            capability="discovery.source",
            provider_name="discovery-source",
            config=config
            if config is not None
            else {"sources": [{"url": _SOURCE_URL, "category": "camera-deals"}]},
        )
    )
    return effects


class _Transport:
    """One canned HTTP response for every GET."""

    def __init__(self, *, status_code: int = 200, text: str, content_type: str) -> None:
        self._status = status_code
        self._text = text
        self._type = content_type
        self.urls: list[str] = []

    def response(self) -> object:
        status = self._status
        response_headers = {"content-type": self._type}
        response_text = self._text

        class _Response:
            status_code = status
            headers = response_headers
            text = response_text

        return _Response()

    def client(self) -> type:
        transport = self

        class _Client:
            # The pooled shared_client probes `is_closed` on cache hits.
            is_closed = False

            def __init__(self, *args: object, **kwargs: object) -> None: ...

            async def __aenter__(self) -> _Client:
                return self

            async def __aexit__(self, *args: object) -> None:
                return None

            async def get(self, url: str, **kwargs: object) -> object:
                transport.urls.append(url)
                return transport.response()

        return _Client


def _with_transport(monkeypatch: pytest.MonkeyPatch, transport: _Transport) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", transport.client())


_RSS = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Carbon fiber tripod review</title><link>https://feeds.example.com/a</link>
<guid>a1</guid><description>great legs for long lenses</description>
<pubDate>Mon, 23 Nov 2026 10:00:00 GMT</pubDate></item>
<item><title>Stale item</title><link>https://feeds.example.com/b</link>
<guid>b1</guid><description>old</description>
<pubDate>Mon, 23 Nov 2025 10:00:00 GMT</pubDate></item>
</channel></rss>"""

_ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><id>x1</id><title>Atom entry</title><link href="https://feeds.example.com/x"/>
<summary>an atom summary</summary><published>2026-11-23T09:00:00Z</published></entry>
</feed>"""

_JSON_FEED = """{"items": [
  {"id": "j1", "url": "https://feeds.example.com/j", "title": "Lens deal",
   "summary": "70-200 sale", "published_at": "2026-11-23T08:00:00Z",
   "expires_at": "2026-12-01T00:00:00Z", "category": "lens"}
]}"""


# ---------------------------------------------------------------------------
# Provider: the Binding allowlist is the allow/deny control
# ---------------------------------------------------------------------------


async def test_provider_refuses_a_binding_that_declares_no_sources() -> None:
    from maistro.capabilities.types import Unavailable

    effects = await _effects_with_source(config={"sources": []})
    binding = await effects.bindings.get("dsrc-1")
    assert binding is not None
    resolved = await resolve_discovery_source_provider(binding)
    assert isinstance(resolved, Unavailable)
    assert "sources" in resolved.reason


async def test_fetch_refuses_a_url_the_binding_never_declared_before_any_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = await _effects_with_source()
    binding = await effects.bindings.get("dsrc-1")
    assert binding is not None
    transport = _Transport(text=_RSS, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    with pytest.raises(PermissionError, match="allowlist"):
        await execute_discovery_source(
            await _resolve_provider(effects),
            DiscoverySourceRequest(url="https://elsewhere.example.com/feed", max_entries=5),
            timeout_s=5.0,
        )
    assert transport.urls == []


async def _resolve_provider(effects: CapabilityEffectContext) -> object:
    binding = await effects.bindings.get("dsrc-1")
    assert binding is not None
    resolved = await resolve_discovery_source_provider(binding)
    assert not isinstance(resolved, type(None))
    return resolved


@pytest.mark.parametrize(
    ("body", "content_type", "expected_title"),
    [
        (_RSS, "application/rss+xml", "Carbon fiber tripod review"),
        (_ATOM, "application/atom+xml", "Atom entry"),
        (_JSON_FEED, "application/json", "Lens deal"),
    ],
)
async def test_fetch_parses_rss_atom_and_json_feeds(
    monkeypatch: pytest.MonkeyPatch, body: str, content_type: str, expected_title: str
) -> None:
    effects = await _effects_with_source()
    transport = _Transport(text=body, content_type=content_type)
    _with_transport(monkeypatch, transport)
    invocation = await invoke_discovery_source(
        effects,
        binding=await effects.bindings.get("dsrc-1"),  # type: ignore[arg-type]
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="attempt-1",
        effect_key=f"discovery.source.fetch:{_SOURCE_URL}:20",
        request=DiscoverySourceRequest(url=_SOURCE_URL, max_entries=20),
        timeout_s=5.0,
        actor_id="user-1",
    )
    result = invocation.result
    assert isinstance(result, dict)
    assert result["count"] >= 1
    assert result["entries"][0]["title"] == expected_title
    # Provenance: every entry carries its source and the fetch stamp.
    for entry in result["entries"]:
        assert entry["source_url"] == _SOURCE_URL
        assert entry.get("fetched_at") or "fetched_at" in result
    assert result["category"] == "camera-deals"


async def test_one_fetch_is_one_recorded_invocation_per_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = await _effects_with_source(
        config={
            "sources": [
                {"url": _SOURCE_URL, "category": "a"},
                {"url": "https://feeds.example.com/rss2", "category": "b"},
            ]
        }
    )
    transport = _Transport(text=_RSS, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    node = DiscoverySourceFetchNode(effect_context=effects)
    result = await node.run({"binding_id": "dsrc-1", "max_age_hours": 0}, _ctx())
    assert result.success
    assert result.output.sources_queried == 2
    assert len(result.output.sources) == 2
    history = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="nr-n1",
        binding_id="dsrc-1",
        effect_key=f"discovery.source.fetch:{_SOURCE_URL}:20",
    )
    assert len(history) == 1
    assert history[0].workspace_id == _WS


async def test_fetch_drops_stale_entries_and_caps_the_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dates are generated relative to now, in RFC 2822 (RSS pubDate) form:
    the staleness rule must hold against wall-clock time, not a fixture that
    silently expires.
    """
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    now = datetime.now(UTC)
    fresh = format_datetime(now - timedelta(hours=2))
    stale = format_datetime(now - timedelta(days=400))
    body = (
        '<rss version="2.0"><channel>'
        f"<item><title>Fresh</title><link>https://feeds.example.com/f</link>"
        f"<guid>f1</guid><description>x</description><pubDate>{fresh}</pubDate></item>"
        f"<item><title>Old</title><link>https://feeds.example.com/o</link>"
        f"<guid>o1</guid><description>y</description><pubDate>{stale}</pubDate></item>"
        "</channel></rss>"
    )
    effects = await _effects_with_source()
    transport = _Transport(text=body, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    node = DiscoverySourceFetchNode(effect_context=effects)
    result = await node.run({"binding_id": "dsrc-1", "max_age_hours": 24 * 30, "limit": 5}, _ctx())
    assert result.success
    assert result.output.skipped_stale == 1
    assert [entry["title"] for entry in result.output.entries] == ["Fresh"]
    # The cycle cap holds even when the feed offers more fresh entries: the
    # provider returns at most `limit` entries and the node keeps that cap.
    fresh_again = body.replace("Old", "Fresh2").replace("/o<", "/f2<").replace("o1", "f2")
    transport2 = _Transport(text=fresh_again, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport2)
    result2 = await node.run({"binding_id": "dsrc-1", "max_age_hours": 24 * 30, "limit": 1}, _ctx())
    assert len(result2.output.entries) == 1


async def test_fetch_without_any_binding_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    transport = _Transport(text=_RSS, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    node = DiscoverySourceFetchNode(effect_context=effects)
    result = await node.run({"binding_id": ""}, _ctx())
    assert not result.success
    assert result.error_code == "BindingNotFound"
    assert transport.urls == []


async def test_budget_exhaustion_is_a_clean_refusal_output(monkeypatch: pytest.MonkeyPatch) -> None:
    effects = await _effects_with_source()
    transport = _Transport(text=_RSS, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    cycle = _Cycle(DiscoveryCycleContext(budget_refusal="discovery_cycle_budget_exhausted"))
    node = DiscoverySourceFetchNode(effect_context=effects, discovery_context=cycle)
    result = await node.run({"binding_id": ""}, _ctx())
    assert result.success  # a refusal is an honest outcome, not a failure
    assert result.output.refusal == "discovery_cycle_budget_exhausted"
    assert result.output.entries == []
    assert transport.urls == []


async def test_fetch_resolves_the_workspace_binding_from_the_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scheduled fire has no HTTP caller: the context carries the Binding id."""
    effects = await _effects_with_source()
    transport = _Transport(text=_RSS, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    cycle = _Cycle(DiscoveryCycleContext(source_binding_id="dsrc-1"))
    node = DiscoverySourceFetchNode(effect_context=effects, discovery_context=cycle)
    result = await node.run({"binding_id": ""}, _ctx())
    assert result.success
    assert len(result.output.entries) >= 1
    assert result.output.sources[0]["category"] == "camera-deals"


# ---------------------------------------------------------------------------
# Scout: the cheap tier — dedupe, topics, feedback down-weights, floor
# ---------------------------------------------------------------------------


def _entry(title: str, url: str, category: str = "camera-deals") -> dict[str, str]:
    return {
        "id": url.rsplit("/", 1)[-1],
        "url": url,
        "title": title,
        "summary": "",
        "category": category,
        "source_url": _SOURCE_URL,
        "published_at": "",
    }


async def test_scout_scores_topic_overlap_and_carries_the_evidence() -> None:
    cycle = _Cycle(DiscoveryCycleContext(watch_topics=("tripod", "lens")))
    node = DiscoveryScoutNode(discovery_context=cycle)
    result = await node.run(
        {
            "entries": [_entry("Carbon tripod stand", "https://x.example.com/1")],
            "min_score": 0.1,
        },
        _ctx("n2"),
    )
    assert result.success
    assert len(result.output.candidates) == 1
    candidate = result.output.candidates[0]
    assert candidate.matched_topics == ["tripod"]
    assert candidate.score == pytest.approx(0.5)


async def test_scout_suppresses_seen_fingerprints_from_the_ledger() -> None:
    fresh = _entry("Fresh", "https://x.example.com/fresh")
    seen_fp = fingerprint_for(entry_id="s1", url="https://x.example.com/seen", title="Seen")
    cycle = _Cycle(DiscoveryCycleContext(seen_fingerprints=frozenset({seen_fp})))
    node = DiscoveryScoutNode(discovery_context=cycle)
    result = await node.run(
        {
            "entries": [
                fresh,
                _entry("Seen", "https://x.example.com/seen"),
                dict(_entry("Fresh again", "https://x.example.com/fresh")),
            ],
            "min_score": 0.0,
        },
        _ctx("n2"),
    )
    assert result.success
    # The ledger fingerprint and the in-cycle duplicate are both suppressed.
    assert result.output.seen_suppressed == 2
    assert [c.title for c in result.output.candidates] == ["Fresh"]


async def test_scout_applies_category_downweights_from_feedback() -> None:
    entry = _entry("Tripod deal", "https://x.example.com/d", category="news")
    context = DiscoveryCycleContext(watch_topics=("tripod",), category_downweights=(("news", 0.0),))
    node = DiscoveryScoutNode(discovery_context=_Cycle(context))
    result = await node.run({"entries": [entry], "min_score": 0.1}, _ctx("n2"))
    assert result.success
    # A fully-dismissed category scores zero: below the floor, suppressed.
    assert result.output.candidates == []
    assert result.output.below_floor == 1


async def test_scout_context_may_narrow_but_never_widen_the_cycle_cap() -> None:
    entries = [_entry(f"Item {i} tripod", f"https://x.example.com/{i}") for i in range(5)]
    context = DiscoveryCycleContext(watch_topics=("tripod",), max_candidates=2)
    node = DiscoveryScoutNode(discovery_context=_Cycle(context))
    result = await node.run(
        {"entries": entries, "max_candidates": 50, "min_score": 0.1}, _ctx("n2")
    )
    assert len(result.output.candidates) == 2


# ---------------------------------------------------------------------------
# Curator: the stronger tier — model verdicts, lexical fallback, evidence
# ---------------------------------------------------------------------------


def _candidate(title: str, url: str, topics: list[str]) -> dict[str, object]:
    from maistro.graph.nodes.discovery_scout import ScoutedCandidate

    return ScoutedCandidate(
        fingerprint=fingerprint_for(entry_id=url, url=url, title=title),
        entry_id=url,
        url=url,
        title=title,
        category="deals",
        matched_topics=topics,
        score=0.5,
    ).model_dump()


_VERDICT_TEMPLATE = (
    '{"candidates": [{"fingerprint": "%s", "relevance": 0.9, "novelty": 0.8, '
    '"confidence": 0.9, "reason": "matches the known tripod plan"}]}'
)


def _verdict_body_for(prompt: object) -> dict[str, object]:
    """The gateway response body scoring the one candidate in the prompt."""
    import json

    payload = json.loads(str(prompt))
    fingerprint = str(payload["candidates"][0]["fingerprint"])
    return {
        "model": "gemini-3.1-flash",
        "choices": [{"message": {"content": _VERDICT_TEMPLATE % fingerprint}}],
        "usage": {"prompt_tokens": 900, "completion_tokens": 60},
    }


@pytest.fixture
async def curator_binding() -> str:
    """The governed model.chat Binding the curator resolves (#56 pattern)."""

    from datetime import UTC, datetime

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.effect_context import default_effect_context
    from maistro.capabilities.providers.llm_gateway import (
        DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    )
    from maistro.credentials.types import CredentialRecord

    effects = default_effect_context()
    await effects.bindings.put(
        Binding(
            created_at=datetime(2026, 9, 1, tzinfo=UTC),
            binding_id="model-b",
            workspace_id=_WS,
            project_id=_PROJECT,
            capability="model.chat",
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        )
    )
    effects.credentials.add(
        workspace_id=_WS,
        project_id=_PROJECT,
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    return "model-b"


def _curator_node() -> DiscoveryCurateNode:
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter
    from maistro.providers.types import ModelMetadata

    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="gemini-3.1-flash",
                provider="test-gateway",
                cost_per_1k_input=0.1,
                cost_per_1k_output=0.2,
                latency_p50_ms=100,
            )
        ]
    )
    return DiscoveryCurateNode(registry=registry, router=CostAwareRouter(registry))


async def test_curator_model_strategy_scores_via_one_governed_call(
    monkeypatch: pytest.MonkeyPatch,
    curator_binding: str,
) -> None:
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    candidate = _candidate("Tripod sale", "https://x.example.com/sale", ["tripod"])
    seen: dict[str, object] = {}

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, object]:
            return _verdict_body_for(seen["body"]["messages"][1]["content"])

    class _Client:
        is_closed = False

        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> _Resp:
            seen["url"] = url
            seen["body"] = kwargs.get("json")
            seen["headers"] = kwargs.get("headers")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    node = _curator_node()
    result = await node.run(
        {
            "candidates": [candidate],
            "strategy": "model",
            "binding_id": curator_binding,
            "context_notes": ["current goal: replace the tripod"],
        },
        _ctx("n3"),
    )
    assert result.success, result.error_message
    assert result.output.strategy == "model"
    assert len(result.output.items) == 1
    item = result.output.items[0]
    assert item.relevance == pytest.approx(0.9)
    assert "tripod plan" in item.explain
    # One governed completion carried the whole small candidate set once,
    # with the context notes in the prompt.
    assert str(seen["url"]).endswith("/v1/chat/completions")
    user_content = str(seen["body"]["messages"][1]["content"])
    assert "Tripod sale" in user_content
    assert "replace the tripod" in user_content
    # The Invocation records the model call in the ledger.
    from maistro.capabilities.effect_context import default_effect_context
    from maistro.graph.nodes.base import replay_effect_key

    effects = default_effect_context()
    history = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="nr-n3",
        binding_id=curator_binding,
        effect_key=replay_effect_key(
            _ctx("n3"), "discovery.curate.complete", {"model": "gemini-3.1-flash"}
        ),
    )
    assert len(history) == 1


async def test_curator_drops_candidates_the_model_does_not_verdict(
    monkeypatch: pytest.MonkeyPatch,
    curator_binding: str,
) -> None:
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    candidate = _candidate("Unknown item", "https://x.example.com/u", [])

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"candidates": []}'}}]}

    class _Client:
        is_closed = False

        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    node = _curator_node()
    result = await node.run(
        {
            "candidates": [candidate],
            "strategy": "model",
            "binding_id": curator_binding,
        },
        _ctx("n3"),
    )
    assert result.success
    assert result.output.items == []
    # An unparsable or absent verdict drops the candidate; it never guesses.
    assert result.output.dropped_unparsable == 1


async def test_curator_model_strategy_refuses_without_a_binding() -> None:
    node = DiscoveryCurateNode(discovery_context=_no_context())
    result = await node.run(
        {"candidates": [_candidate("X", "https://x.example.com/x", [])], "strategy": "model"},
        _ctx("n3"),
    )
    assert not result.success
    assert result.error_code == "BindingNotFound"


async def test_curator_lexical_strategy_needs_no_model_and_records_the_strategy() -> None:
    node = DiscoveryCurateNode(discovery_context=_no_context())
    result = await node.run(
        {
            "candidates": [
                _candidate("Tripod deal", "https://x.example.com/t", ["tripod"]),
                _candidate("Unrelated", "https://x.example.com/u", []),
            ],
            "strategy": "lexical",
            "context_notes": ["current goal: buy a tripod this month"],
            "min_confidence": 0.3,
        },
        _ctx("n3"),
    )
    assert result.success
    assert result.output.strategy == "lexical"
    assert len(result.output.items) == 1
    item = result.output.items[0]
    assert item.strategy == "lexical"
    assert "tripod" in item.explain
    assert "buy a tripod" in item.matched_context[0]


async def test_curator_with_no_candidates_spends_no_model_call(
    monkeypatch: pytest.MonkeyPatch,
    curator_binding: str,
) -> None:
    node = _curator_node()

    class _NoPost:
        is_closed = False

        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def __aenter__(self) -> _NoPost:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> object:
            raise AssertionError("no candidates means no curator spend")

    monkeypatch.setattr(httpx, "AsyncClient", _NoPost)
    result = await node.run(
        {"candidates": [], "strategy": "model", "binding_id": curator_binding}, _ctx("n3")
    )
    assert result.success
    assert result.output.items == []


async def test_source_declared_expiry_is_the_only_deadline_evidence() -> None:
    from maistro.graph.nodes.discovery_scout import ScoutedCandidate

    with_expiry = ScoutedCandidate(
        fingerprint="fp-exp",
        entry_id="e",
        url="https://x.example.com/e",
        title="Lens sale ends soon",
        category="deals",
        expires_at="2026-12-01T00:00:00Z",
        score=0.5,
        matched_topics=["sale"],
    )
    without_expiry = with_expiry.model_copy(update={"fingerprint": "fp-plain", "expires_at": ""})
    node = DiscoveryCurateNode(discovery_context=_no_context())
    result = await node.run(
        {
            "candidates": [with_expiry.model_dump(), without_expiry.model_dump()],
            "strategy": "lexical",
            "min_confidence": 0.0,
            "context_notes": ["watching: lens sale"],
        },
        _ctx("n3"),
    )
    assert result.success
    by_fp = {item.fingerprint: item for item in result.output.items}
    # The expiry passes through untouched; nothing invents one for items
    # whose source declared none.
    assert by_fp["fp-exp"].expires_at == "2026-12-01T00:00:00Z"
    assert by_fp["fp-plain"].expires_at == ""


async def test_curator_caps_the_surfaced_set_from_context() -> None:
    node = DiscoveryCurateNode(discovery_context=_Cycle(DiscoveryCycleContext(max_surfaced=1)))
    candidates = [_candidate(f"Deal {i}", f"https://x.example.com/{i}", ["deal"]) for i in range(4)]
    result = await node.run(
        {
            "candidates": candidates,
            "strategy": "lexical",
            "max_surfaced": 10,
            "min_confidence": 0.0,
            "context_notes": ["watching deals"],
        },
        _ctx("n3"),
    )
    assert len(result.output.items) == 1


# ---------------------------------------------------------------------------
# Seed + context defaults
# ---------------------------------------------------------------------------


def test_seed_is_a_valid_dag_of_registered_kinds() -> None:
    seed = proactive_discovery_seed()
    report = validate_dag(seed)
    assert report.findings == []
    kinds = {node["kind"] for node in seed["nodes"]}
    assert kinds == {"discovery.source_fetch", "discovery.scout", "discovery.curate"}


def test_seed_ships_fail_closed_defaults() -> None:
    seed = proactive_discovery_seed()
    fetch = seed["nodes"][0]
    assert fetch["inputs"]["binding_id"] == ""
    curate = seed["nodes"][2]
    assert curate["inputs"]["binding_id"] == ""
    assert curate["inputs"]["model"] == ""


async def test_bare_context_provider_provides_nothing() -> None:
    provider = default_discovery_context()
    context = await provider.context_for("ws", "p", "u")
    assert context.watch_topics == ()
    assert context.seen_fingerprints == frozenset()
    assert context.budget_refusal == ""
    assert context.source_binding_id == ""
    assert context.curator_binding_id == ""


def test_budget_exhaustion_is_a_typed_error() -> None:
    assert issubclass(DiscoveryBudgetExhausted, RuntimeError)


def test_fingerprint_is_url_identity_with_content_fallback() -> None:
    assert fingerprint_for(entry_id="a", url="https://x/1", title="t") == fingerprint_for(
        entry_id="b", url="https://x/1", title="other"
    )
    # No URL: the entry id is the identity.
    assert fingerprint_for(entry_id="e1", url="", title="t") == fingerprint_for(
        entry_id="e1", url="", title="ignored"
    )
    # No URL or id: the title is the identity, so different titles differ.
    assert fingerprint_for(entry_id="", url="", title="t") != fingerprint_for(
        entry_id="", url="", title="other"
    )
