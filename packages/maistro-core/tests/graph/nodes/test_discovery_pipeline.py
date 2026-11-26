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
    DiscoverySourceProvider,
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


_RSS_TEMPLATE = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Carbon fiber tripod review</title><link>https://feeds.example.com/a</link>
<guid>a1</guid><description>great legs for long lenses</description>
<pubDate>{fresh}</pubDate></item>
<item><title>Stale item</title><link>https://feeds.example.com/b</link>
<guid>b1</guid><description>old</description>
<pubDate>{stale}</pubDate></item>
</channel></rss>"""


def _rss_body() -> str:
    """The module RSS fixture with dates relative to wall clock, not baked.

    The staleness rule compares each entry's ``pubDate`` against now with a
    72-hour default (``max_age_hours``), so a baked date silently rots: this
    fixture's fresh entry (``Mon, 23 Nov 2026 10:00:00 GMT``) crossed that
    line on 2026-11-26 10:00 GMT — minutes after a verification run had
    collected the suite green — and the fetch dropped both entries as stale.
    Same convention as the staleness test below: relative dates cannot rot.
    """
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    fresh = format_datetime(datetime.now(UTC) - timedelta(hours=2))
    stale = format_datetime(datetime.now(UTC) - timedelta(days=400))
    return _RSS_TEMPLATE.format(fresh=fresh, stale=stale)


_RSS = _rss_body()

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


async def test_a_feed_carrying_entity_declarations_is_refused_not_expanded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared source is still remote content: entities never expand.

    stdlib ElementTree expands internal entities, so a hostile feed could
    hand the scout a billion-laughs document. Parsing goes through
    defusedxml, which refuses entity/DTD declarations outright; the refusal
    is loud (the same "unparseable" classification as a broken feed), and
    no entry is produced from a payload the parser refused.
    """
    effects = await _effects_with_source()
    body = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE rss [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;">]>'
        "<rss><channel><item><title>&lol2;</title>"
        "<link>https://feeds.example.com/x</link></item></channel></rss>"
    )
    transport = _Transport(text=body, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    with pytest.raises(RuntimeError, match="unparseable RSS"):
        await invoke_discovery_source(
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
    # The GET happened (declared origin, policy-allowed); the payload was
    # refused afterwards — nothing expanded, nothing surfaced.
    assert transport.urls == [_SOURCE_URL]


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


async def test_scout_matches_multiword_watch_topics_as_token_sequences() -> None:
    cycle = _Cycle(DiscoveryCycleContext(watch_topics=("machine learning", "tripod")))
    node = DiscoveryScoutNode(discovery_context=cycle)
    result = await node.run(
        {
            "entries": [
                _entry("Advances in machine learning tools", "https://x.example.com/ml"),
                _entry("Unrelated note", "https://x.example.com/none"),
            ],
            "min_score": 0.1,
        },
        _ctx("n2b"),
    )
    assert result.success
    assert len(result.output.candidates) == 1
    candidate = result.output.candidates[0]
    assert candidate.matched_topics == ["machine learning"]
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


# ---------------------------------------------------------------------------
# Cycle key: the reachable path reads the context with the calling Run id
# ---------------------------------------------------------------------------


async def test_every_node_read_carries_the_run_id_as_its_cycle_key() -> None:
    """The charge is the host's to make, but only if it can tell Runs apart.

    This is the link that makes per-Run budget charging reachable at all: a
    host cannot charge idempotently unless each node read names its Run. If a
    node drops the key, this fails while every behavior test stays green —
    exactly the failure mode the Hive ledger shipped with before this pin.
    """
    run_id = _ctx("n2").run_id
    assert run_id  # the executor always names the Run; the pin needs it

    scout_cycle = _Cycle(DiscoveryCycleContext(watch_topics=("tripod",)))
    scout = DiscoveryScoutNode(discovery_context=scout_cycle)
    scout_result = await scout.run(
        {"entries": [_entry("Carbon tripod stand", "https://x.example.com/1")], "min_score": 0.1},
        _ctx("n2"),
    )
    assert scout_result.success
    assert scout_cycle.asked == [run_id]

    curate_cycle = _Cycle(DiscoveryCycleContext())
    curate = DiscoveryCurateNode(discovery_context=curate_cycle)
    curate_result = await curate.run(
        {
            "candidates": [],
            "strategy": "lexical",
        },
        _ctx("n3"),
    )
    assert curate_result.success
    assert curate_cycle.asked == [run_id]

    fetch_cycle = _Cycle(DiscoveryCycleContext(budget_refusal="discovery_disabled"))
    fetch = DiscoverySourceFetchNode(discovery_context=fetch_cycle)
    fetch_result = await fetch.run(
        {"binding_id": "dsrc-1", "limit": 5},
        _ctx("n1"),
    )
    # Even the refusal read names its Run — the host decided *before* any
    # node ran whether this cycle may spend, so it must know which cycle
    # is asking.
    assert fetch_result.output.refusal == "discovery_disabled"
    assert fetch_cycle.asked == [run_id]


# ---------------------------------------------------------------------------
# Redirect hops: the provider rides the guarded shared client (#155)
# ---------------------------------------------------------------------------


class _RedirectingSource(httpx.AsyncBaseTransport):
    """The declared source 302s to a metadata address; anything else answers.

    Deliberately not `httpx.MockTransport`: `guarded()` returns that one
    unwrapped, so a test built on it never reaches the policy at all — the
    exact blind spot this test exists to close for the discovery provider.
    """

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(str(request.url))
        if request.url.host == "feeds.example.com":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
                request=request,
            )
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml"},
            text='<?xml version="1.0"?><rss version="2.0"/>',
            request=request,
        )

    async def aclose(self) -> None:
        return None


async def test_provider_redirect_into_a_private_target_is_refused_at_that_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared feed cannot launder a fetch to an internal target.

    The provider follows redirects (a feed that moved hosts is still the
    declared source), so the control that matters is the outbound policy on
    every hop — the shared client's transport is guarded, and httpx re-enters
    it per hop. The provider must surface that refusal as the honest
    no-effect contract, not as an UNKNOWN outcome on the Invocation ledger.
    """
    from maistro.capabilities.invocation import EffectNotApplied
    from maistro.security.outbound import configure_outbound_policy, reset_outbound_policy

    effects = await _effects_with_source()
    provider = await _resolve_provider(effects)
    inner = _RedirectingSource()
    real_client = httpx.AsyncClient

    def _guarded_client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        from maistro.security.outbound import guarded

        kwargs["transport"] = guarded(inner)  # type: ignore[arg-type]
        return real_client(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx, "AsyncClient", _guarded_client)
    # Hop 0 is the declared origin, allowed by policy so this test needs no
    # DNS; the private hop is validated and refused by address.
    configure_outbound_policy("https://feeds.example.com")
    try:
        with pytest.raises(EffectNotApplied, match="outbound policy"):
            await execute_discovery_source(
                provider,
                DiscoverySourceRequest(url=_SOURCE_URL, max_entries=5),
                timeout_s=5.0,
            )
    finally:
        reset_outbound_policy()
    # Hop 0 was made; the private hop never reached any transport.
    assert inner.seen == [_SOURCE_URL]


# ---------------------------------------------------------------------------
# Provider edges: resolution junk, foreign objects, HTTP failures, feed shapes
# ---------------------------------------------------------------------------


async def test_resolution_skips_malformed_source_rows_and_refuses_an_all_junk_list() -> None:
    """The allowlist parser keeps only {url, category} dict rows with a URL.

    A junk row among valid ones narrows the allowlist; a list of ONLY junk
    rows is the same refusal as an empty one — never an open fetch.
    """
    from maistro.capabilities.types import Unavailable

    mixed = await _effects_with_source(
        config={
            "sources": [
                "https://not-a-dict.example.com",  # type: ignore[list-item]
                {"category": "no url here"},
                {"url": "   ", "category": "blank url"},
                {"url": _SOURCE_URL, "category": "camera-deals"},
            ]
        }
    )
    binding = await mixed.bindings.get("dsrc-1")
    assert binding is not None
    resolved = await resolve_discovery_source_provider(binding)
    assert isinstance(resolved, DiscoverySourceProvider)
    assert tuple(s.url for s in resolved.sources) == (_SOURCE_URL,)
    assert resolved.declared(_SOURCE_URL) is not None
    assert resolved.declared("https://elsewhere.example.com") is None

    all_junk = await _effects_with_source(
        config={"sources": ["just-a-string", {"category": "url-less"}]}  # type: ignore[list-item]
    )
    junk_binding = await all_junk.bindings.get("dsrc-1")
    assert junk_binding is not None
    refused = await resolve_discovery_source_provider(junk_binding)
    assert isinstance(refused, Unavailable)
    assert "sources" in refused.reason

    no_key = await _effects_with_source(config={"allowlist": "wrong key"})
    no_key_binding = await no_key.bindings.get("dsrc-1")
    assert no_key_binding is not None
    refused = await resolve_discovery_source_provider(no_key_binding)
    assert isinstance(refused, Unavailable)
    assert "sources" in refused.reason


async def test_a_binding_pinning_another_provider_name_is_unavailable() -> None:
    from maistro.capabilities.types import Unavailable

    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            binding_id="dsrc-wrong",
            workspace_id=_WS,
            project_id=_PROJECT,
            node_id="n1",
            capability="discovery.source",
            provider_name="pm-polling",
            config={"sources": [{"url": _SOURCE_URL, "category": "a"}]},
        )
    )
    binding = await effects.bindings.get("dsrc-wrong")
    assert binding is not None
    resolved = await resolve_discovery_source_provider(binding)
    assert isinstance(resolved, Unavailable)
    assert "pm-polling" in resolved.reason


async def test_the_capability_seam_refuses_a_binding_of_another_capability() -> None:
    """invoke_discovery_source is wired to the discovery.source capability;
    a Binding of any other capability must fail loudly at that seam."""
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            binding_id="model-x",
            workspace_id=_WS,
            project_id=_PROJECT,
            node_id="n1",
            capability="model.chat",
            config={"sources": [{"url": _SOURCE_URL, "category": "a"}]},
        )
    )
    binding = await effects.bindings.get("model-x")
    assert binding is not None
    with pytest.raises(ValueError, match="unexpected discovery capability"):
        await invoke_discovery_source(
            effects,
            binding=binding,  # type: ignore[arg-type]
            run_id="run-1",
            node_run_id="nr-1",
            attempt_id="attempt-1",
            effect_key="discovery.source.fetch:x",
            request=DiscoverySourceRequest(url=_SOURCE_URL, max_entries=5),
            timeout_s=5.0,
        )


async def test_execution_refuses_foreign_providers_and_requests() -> None:
    effects = await _effects_with_source()
    provider = await _resolve_provider(effects)
    assert isinstance(provider, DiscoverySourceProvider)
    request = DiscoverySourceRequest(url=_SOURCE_URL, max_entries=5)
    with pytest.raises(TypeError, match="foreign provider"):
        await execute_discovery_source(object(), request, timeout_s=5.0)
    with pytest.raises(TypeError, match="foreign request"):
        await execute_discovery_source(provider, {"url": _SOURCE_URL}, timeout_s=5.0)  # type: ignore[arg-type]


async def test_an_http_error_status_is_a_typed_error_carrying_the_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.capabilities.providers.discovery_source import DiscoverySourceHttpError

    effects = await _effects_with_source()
    _with_transport(monkeypatch, _Transport(status_code=404, text="gone", content_type="text/html"))
    with pytest.raises(DiscoverySourceHttpError) as excinfo:
        await execute_discovery_source(
            await _resolve_provider(effects),
            DiscoverySourceRequest(url=_SOURCE_URL, max_entries=5),
            timeout_s=5.0,
        )
    assert excinfo.value.status_code == 404


async def test_an_unreachable_source_is_an_effect_not_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maistro.capabilities.invocation import EffectNotApplied

    effects = await _effects_with_source()

    class _DeadClient:
        is_closed = False

        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def __aenter__(self) -> _DeadClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> object:
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "AsyncClient", _DeadClient)
    with pytest.raises(EffectNotApplied, match="source unreachable"):
        await execute_discovery_source(
            await _resolve_provider(effects),
            DiscoverySourceRequest(url=_SOURCE_URL, max_entries=5),
            timeout_s=5.0,
        )


def test_json_feeds_come_in_both_shapes_and_skip_foreign_rows() -> None:
    from maistro.capabilities.providers.discovery_source import _parse_feed

    as_list = '[{"id": "1", "title": "From a list"}, "not-a-dict"]'
    rows = _parse_feed(_SOURCE_URL, "application/json", as_list, 20)
    assert [row["title"] for row in rows] == ["From a list"]

    as_items = '{"items": [{"id": "2", "title": "From items"}]}'
    rows = _parse_feed(_SOURCE_URL, "application/json", as_items, 20)
    assert [row["title"] for row in rows] == ["From items"]


async def test_unparseable_and_unknown_shaped_feeds_are_loud_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = await _effects_with_source()
    provider = await _resolve_provider(effects)

    effects = await _effects_with_source()
    provider = await _resolve_provider(effects)

    async def _fetch(body: str, content_type: str, timeout_s: float) -> object:
        # The pooled client is keyed by configuration, so each fetch uses a
        # distinct timeout to get its own freshly-patched client.
        _with_transport(monkeypatch, _Transport(text=body, content_type=content_type))
        return await execute_discovery_source(
            provider,
            DiscoverySourceRequest(url=_SOURCE_URL, max_entries=5),
            timeout_s=timeout_s,
        )

    garbage_atom = "this is not <feed at all"
    with pytest.raises(RuntimeError, match="unparseable Atom"):
        await _fetch(garbage_atom, "application/atom+xml", 5.0)

    garbage_json = "{not json"
    with pytest.raises(RuntimeError, match="unparseable JSON"):
        await _fetch(garbage_json, "application/json", 6.0)

    unknown_json = '{"entries": []}'
    with pytest.raises(RuntimeError, match="neither a list nor an object with `items`"):
        await _fetch(unknown_json, "application/json", 7.0)


def test_every_feed_shape_honours_the_per_request_cap() -> None:
    from maistro.capabilities.providers.discovery_source import _parse_feed

    atom_entries = "".join(
        f"<entry><id>e{i}</id><title>Entry {i}</title></entry>" for i in range(4)
    )
    atom = f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{atom_entries}</feed>'
    assert len(_parse_feed(_SOURCE_URL, "application/atom+xml", atom, 2)) == 2

    json_entries = ",".join(f'{{"id": "{i}", "title": "Row {i}"}}' for i in range(4))
    assert len(_parse_feed(_SOURCE_URL, "application/json", f"[{json_entries}]", 3)) == 3


async def test_timestamps_that_cannot_be_read_are_never_treated_as_stale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank, foreign, and timezone-less stamps survive a strict age window."""
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    fresh_rfc822 = format_datetime(datetime.now(UTC) - timedelta(hours=2))
    body = (
        '<rss version="2.0"><channel>'
        f"<item><title>Blank stamp</title><link>https://feeds.example.com/b</link>"
        f"<guid>b1</guid><description>x</description></item>"
        f"<item><title>Foreign stamp</title><link>https://feeds.example.com/f</link>"
        f"<guid>f1</guid><description>x</description><pubDate>yesterday, maybe</pubDate></item>"
        f"<item><title>Naive iso stamp</title><link>https://feeds.example.com/n</link>"
        f"<guid>n1</guid><description>x</description>"
        f"<pubDate>{datetime.now(UTC).replace(tzinfo=None).isoformat()}</pubDate></item>"
        f"<item><title>Rfc stamp</title><link>https://feeds.example.com/r</link>"
        f"<guid>r1</guid><description>x</description><pubDate>{fresh_rfc822}</pubDate></item>"
        "</channel></rss>"
    )
    effects = await _effects_with_source()
    _with_transport(monkeypatch, _Transport(text=body, content_type="application/rss+xml"))
    node = DiscoverySourceFetchNode(effect_context=effects)
    result = await node.run({"binding_id": "dsrc-1", "max_age_hours": 24, "limit": 10}, _ctx())
    assert result.success
    # Nothing was dropped: unreadable time is not old time.
    assert result.output.skipped_stale == 0
    titles = {entry["title"] for entry in result.output.entries}
    assert titles == {"Blank stamp", "Foreign stamp", "Naive iso stamp", "Rfc stamp"}


async def test_fetch_refuses_a_binding_whose_declared_rows_are_all_junk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    effects = await _effects_with_source(
        config={"sources": ["a-string", {"category": "no url"}]}  # type: ignore[list-item]
    )
    transport = _Transport(text=_RSS, content_type="application/rss+xml")
    _with_transport(monkeypatch, transport)
    node = DiscoverySourceFetchNode(effect_context=effects)
    result = await node.run({"binding_id": "dsrc-1"}, _ctx())
    assert not result.success
    assert result.error_code == "BindingNotFound"
    assert transport.urls == []


async def test_fetch_ignores_foreign_rows_backfills_categories_and_honours_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-dict rows are skipped, missing categories come from the Binding's
    declared source, and the cycle cap stops further sources."""
    effects = await _effects_with_source(
        config={
            "sources": [
                {"url": _SOURCE_URL, "category": "camera-deals"},
                {"url": "https://feeds.example.com/rss2", "category": "b"},
            ]
        }
    )
    body = '["not-a-dict", {"id": "1", "title": "No category"}, {"id": "2", "title": "Second"}]'
    _with_transport(monkeypatch, _Transport(text=body, content_type="application/json"))
    node = DiscoverySourceFetchNode(effect_context=effects)
    result = await node.run({"binding_id": "dsrc-1", "max_age_hours": 0, "limit": 2}, _ctx())
    assert result.success
    entries = result.output.entries
    assert [entry["title"] for entry in entries] == ["No category", "Second"]
    # The Binding's declared category backfills what the feed omitted.
    assert all(entry["category"] == "camera-deals" for entry in entries)
    # The cap stopped the cycle at 2: the second declared source was never
    # queried.
    assert result.output.sources_queried == 1
    assert result.output.sources[0]["url"] == _SOURCE_URL


def test_accept_entries_skips_foreign_rows_caps_remaining_and_keeps_declared_categories() -> None:
    """The accept loop is the node's own defense line: a foreign row (or a
    remaining-cap of zero) never becomes an entry, and an entry the feed
    already categorized keeps that category instead of the Binding's."""
    from datetime import UTC, datetime

    from maistro.graph.nodes.discovery_source_fetch import DiscoverySourceFetchIn

    node = DiscoverySourceFetchNode(effect_context=new_in_memory_effect_context())
    inputs = DiscoverySourceFetchIn(binding_id="dsrc-1", max_age_hours=0, limit=5)
    now = datetime.now(UTC)

    rows, skipped = node._accept_entries(
        {"entries": ["not-a-dict", {"id": "1", "title": "Kept"}]},
        "camera-deals",
        now=now,
        inputs=inputs,
        remaining=5,
    )
    assert skipped == 0
    assert [row["title"] for row in rows] == ["Kept"]
    assert rows[0]["category"] == "camera-deals"

    # A remaining-cap of zero drops every row without raising.
    rows, skipped = node._accept_entries(
        {"entries": [{"id": "2", "title": "Over cap"}]},
        "camera-deals",
        now=now,
        inputs=inputs,
        remaining=0,
    )
    assert rows == []
    assert skipped == 0

    # An entry already carrying its feed's category keeps it.
    rows, _ = node._accept_entries(
        {"entries": [{"id": "3", "title": "Categorized", "category": "feed-category"}]},
        "camera-deals",
        now=now,
        inputs=inputs,
        remaining=5,
    )
    assert rows[0]["category"] == "feed-category"


# ---------------------------------------------------------------------------
# Curator edges: strict verdict shapes, honest drops, refusal, strategy
# ---------------------------------------------------------------------------


def test_verdict_parsing_is_strict_about_shapes() -> None:
    from maistro.graph.nodes.discovery_curate import _parse_verdicts, _score_triple

    assert _parse_verdicts("the model rambled; no JSON at all") == {}
    assert _parse_verdicts('{"candidates": broken}') == {}
    assert _parse_verdicts('{"candidates": "everything is fine"}') == {}
    assert _parse_verdicts('["a bare list is not a verdict"]') == {}
    # Non-dict rows and rows without a string fingerprint are skipped.
    parsed = _parse_verdicts('{"candidates": ["junk", {"fingerprint": 7}, {"fingerprint": "ok"}]}')
    assert list(parsed) == ["ok"]

    # Score triples: booleans, strings and out-of-range numbers are all
    # refused; every field present and in range passes.
    good = {"relevance": 0.9, "novelty": 0.8, "confidence": 0.7, "reason": "r"}
    assert _score_triple(good) == (0.9, 0.8, 0.7, "r")
    assert _score_triple({**good, "relevance": True}) is None
    assert _score_triple({**good, "novelty": "0.8"}) is None
    assert _score_triple({**good, "confidence": 1.5}) is None
    assert _score_triple({"relevance": 0.9, "novelty": 0.8}) is None


def test_lexical_notes_without_salient_words_score_nothing() -> None:
    from maistro.graph.nodes.discovery_curate import _lexical_matches
    from maistro.graph.nodes.discovery_scout import ScoutedCandidate

    scouted = ScoutedCandidate.model_validate(
        _candidate("Tripod deal", "https://x.example.com/t", ["tripod"])
    )
    # Stop-words only: nothing counts as an overlap hit.
    score, matched = _lexical_matches(scouted, ["the a an of to"])
    assert score == 0.0
    assert matched == []


async def test_verdict_shapes_are_scored_honestly_through_the_node(
    monkeypatch: pytest.MonkeyPatch,
    curator_binding: str,
) -> None:
    """A parseable verdict below the floor is a low-confidence drop, an
    unparsable one is an unparsable drop, and a kept verdict without a reason
    text adds no fabricated curator evidence."""
    import json as _json

    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    low_fp = fingerprint_for(entry_id="lo", url="https://x.example.com/low", title="Low conf")
    bad_fp = fingerprint_for(entry_id="ba", url="https://x.example.com/bad", title="Bad triple")
    quiet_fp = fingerprint_for(entry_id="qu", url="https://x.example.com/quiet", title="Quiet")

    def _verdict_body_for(prompt: object) -> str:
        """Verdicts for every candidate in the prompt — one completion, one
        verdict per candidate, each in the shape that candidate tests."""
        payload = _json.loads(str(prompt))
        rows: list[dict[str, object]] = []
        for row in payload["candidates"]:
            fingerprint = str(row["fingerprint"])
            if fingerprint == low_fp:
                rows.append(
                    {
                        "fingerprint": fingerprint,
                        "relevance": 0.9,
                        "novelty": 0.8,
                        "confidence": 0.1,
                        "reason": "weak",
                    }
                )
            elif fingerprint == bad_fp:
                rows.append(
                    {
                        "fingerprint": fingerprint,
                        "relevance": True,
                        "novelty": 0.8,
                        "confidence": 0.9,
                        "reason": "bad",
                    }
                )
            else:
                rows.append(
                    {
                        "fingerprint": fingerprint,
                        "relevance": 0.9,
                        "novelty": 0.8,
                        "confidence": 0.9,
                    }
                )
        return _json.dumps({"candidates": rows})

    seen: dict[str, object] = {}

    class _EchoResp:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {
                "choices": [
                    {
                        "message": {
                            "content": _verdict_body_for(seen["body"]["messages"][1]["content"])
                        }
                    }
                ]
            }

    class _EchoClient:
        is_closed = False

        def __init__(self, *args: object, **kwargs: object) -> None: ...

        async def __aenter__(self) -> _EchoClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, **kwargs: object) -> _EchoResp:
            seen["body"] = kwargs.get("json")
            return _EchoResp()

    monkeypatch.setattr(httpx, "AsyncClient", _EchoClient)
    node = _curator_node()
    result = await node.run(
        {
            "candidates": [
                _candidate("Low conf", "https://x.example.com/low", []),
                _candidate("Bad triple", "https://x.example.com/bad", []),
                _candidate("Quiet", "https://x.example.com/quiet", []),
            ],
            "strategy": "model",
            "binding_id": curator_binding,
            "min_confidence": 0.5,
        },
        _ctx("n3"),
    )
    assert result.success
    # One item survives: the quiet verdict with full scores and no reason.
    assert [item.fingerprint for item in result.output.items] == [quiet_fp]
    kept = result.output.items[0]
    assert "curator:" not in kept.explain
    assert kept.matched_context == []
    # The other two are dropped into their honest buckets.
    assert result.output.dropped_low_confidence == 1
    assert result.output.dropped_unparsable == 1


async def test_a_budget_refusal_is_the_curator_output_not_a_failure() -> None:
    cycle = _Cycle(DiscoveryCycleContext(budget_refusal="discovery_cycle_budget_exhausted"))
    node = DiscoveryCurateNode(discovery_context=cycle)
    result = await node.run(
        {
            "candidates": [_candidate("X", "https://x.example.com/x", [])],
            "strategy": "lexical",
        },
        _ctx("n3"),
    )
    assert result.success
    assert result.output.items == []
    assert result.output.strategy == "refused:discovery_cycle_budget_exhausted"


async def test_an_unknown_strategy_is_a_node_error() -> None:
    node = DiscoveryCurateNode(discovery_context=_no_context())
    result = await node.run(
        {
            "candidates": [_candidate("X", "https://x.example.com/x", [])],
            "strategy": "psychic",
        },
        _ctx("n3"),
    )
    assert not result.success
    assert "model|lexical" in (result.error_message or "")
