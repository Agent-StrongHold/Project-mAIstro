"""LLM query expansion: governed egress and corpus oversight.

Two contracts: the expander *raises* on failure (a silently-empty
expansion would disguise an outage as "the model found nothing"), and
the searcher treats expansion output as *candidates* that corpus
statistics can still veto. The HTTP seam is faked at
`execute_model_chat` — the one governed model-egress call the expander
is allowed to use (quality/model-egress.json) — the same seam
maistro-core's gateway tests fake, so no test touches a network.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.providers.llm_gateway import (
    GatewayEndpoint,
    LlmAuthError,
    LlmGatewayProvider,
    LlmHttpError,
    ModelChatRequest,
)
from maistro_registry.retrieval import (
    ExpansionError,
    NoExpansion,
    OpenAICompatExpander,
    RetrievalSearcher,
    build_index,
    load_corpus,
)
from maistro_registry.retrieval import expand as expand_module


def _completion(text: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": text}}]}


class _Gateway:
    """Stands in for `execute_model_chat` and records what crossed it."""

    def __init__(
        self,
        body: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.body = body
        self.error = error
        self.calls: list[tuple[LlmGatewayProvider, ModelChatRequest, GatewayEndpoint]] = []

    async def __call__(
        self,
        provider: LlmGatewayProvider,
        request: ModelChatRequest,
        *,
        endpoint: GatewayEndpoint,
    ) -> dict[str, Any]:
        self.calls.append((provider, request, endpoint))
        if self.error is not None:
            raise self.error
        assert self.body is not None, "fake gateway needs a body or an error"
        return self.body


def _install(
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> _Gateway:
    gateway = _Gateway(body=body, error=error)
    monkeypatch.setattr(expand_module, "execute_model_chat", gateway)
    return gateway


def _expander() -> OpenAICompatExpander:
    return OpenAICompatExpander(base_url="http://llm.test/v1", model="test-model", api_key="k")


def test_expander_sends_a_governed_request_and_parses_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _install(monkeypatch, _completion('["queue recovery", "TaskRecord"]'))
    terms = _expander().expand("task queue restart")
    assert terms == ["queue recovery", "TaskRecord"]

    provider, request, endpoint = gateway.calls[0]
    # The egress is the approved gateway Provider, pinned to the asked model.
    assert isinstance(provider, LlmGatewayProvider)
    assert provider.name == "test-model"
    assert request.temperature == 0
    assert request.max_tokens == 200
    assert [m["role"] for m in request.messages] == ["system", "user"]
    # Credential stays on the endpoint, never in the request payload.
    assert endpoint.api_key == "k"
    assert endpoint.base_url == "http://llm.test/v1"


def test_expander_tolerates_fenced_array(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _completion('```json\n["a term"]\n```'))
    assert _expander().expand("q") == ["a term"]


@pytest.mark.parametrize(
    "payload",
    [
        _completion("no array here at all"),
        _completion("[not json"),
        {"choices": []},
        {"unrelated": True},
    ],
)
def test_expander_raises_on_unusable_output(monkeypatch: pytest.MonkeyPatch, payload: Any) -> None:
    _install(monkeypatch, payload)
    with pytest.raises(ExpansionError):
        _expander().expand("q")


def test_expander_rejects_non_string_completion_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-string completion payload is a failure, never a best guess."""
    _install(monkeypatch, {"choices": [{"message": {"content": 123}}]})
    with pytest.raises(ExpansionError, match="not a string"):
        _expander().expand("q")


def test_expander_drops_non_string_blank_and_duplicate_terms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Term cleanup: non-strings, blanks and duplicates never reach the index."""
    _install(monkeypatch, _completion('["queue", 42, "  ", "queue", null]'))
    assert _expander().expand("q") == ["queue"]


def test_expander_rejects_fenced_prose_without_an_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fence whose chunks hold no array still ends in ExpansionError."""
    _install(monkeypatch, _completion("```text\nplain prose, no brackets\n```"))
    with pytest.raises(ExpansionError, match="no JSON array"):
        _expander().expand("q")


def test_expander_maps_gateway_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, error=LlmAuthError("llm_auth_failed status=401", status_code=401))
    with pytest.raises(ExpansionError, match="expansion request failed"):
        _expander().expand("q")


def test_expander_maps_gateway_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, error=LlmHttpError("llm_rate_limited status=429", status_code=429))
    with pytest.raises(ExpansionError, match="expansion request failed"):
        _expander().expand("q")


def test_expander_maps_unreachable_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, error=EffectNotApplied("model gateway unreachable, no effect occurred"))
    with pytest.raises(ExpansionError, match="expansion request failed"):
        _expander().expand("q")


def test_expander_requires_base_url_and_model() -> None:
    with pytest.raises(ValueError, match="base_url"):
        OpenAICompatExpander(base_url="", model="m")
    with pytest.raises(ValueError, match="model"):
        OpenAICompatExpander(base_url="http://x", model="")


def test_api_key_defaults_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAISTRO_EXPAND_API_KEY", "env-key")
    gateway = _install(monkeypatch, _completion("[]"))
    OpenAICompatExpander(base_url="http://llm.test", model="m").expand("q")
    # A root without /v1 is normalized by GatewayEndpoint on the governed path.
    assert gateway.calls[0][2].api_key == "env-key"
    assert gateway.calls[0][2].base_url == "http://llm.test"


def test_no_expansion_contributes_nothing() -> None:
    assert NoExpansion().expand("anything") == []


def _repo(tmp_path: Path, make_doc: object) -> Path:
    # Four documents so topic terms stay below the 0.5 df-share ceiling
    # while "durable" (2/4 = 0.5, at the ceiling) is rejected — the
    # corpus-glue case the expansion filter must catch.
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-queue.md",
        "ADR-001",
        "Queue discipline",
        body="Tasks queue for durable work.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-002-vault.md",
        "ADR-002",
        "Vault of secrets",
        body="Vault prose about durable secrets.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-003-render.md",
        "ADR-003",
        "Rendering pipeline",
        body="Pixels are composited per frame.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-004-network.md",
        "ADR-004",
        "Networking substrate",
        body="Peers exchange envelopes.",
    )
    return tmp_path


def test_searcher_falls_back_when_expansion_fails(
    tmp_path: Path, make_doc: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, error=EffectNotApplied("model gateway unreachable, no effect occurred"))
    searcher = RetrievalSearcher(build_index(load_corpus(_repo(tmp_path, make_doc))))
    response = searcher.search("queue", k=2, expander=_expander())
    assert response.expansion_skipped is True
    assert response.expansion_error is not None
    # Lexical-only results are still returned: degradation, not failure.
    assert [r.doc_id for r in response.results] == ["ADR-001"]


def test_expansion_terms_face_corpus_statistics(tmp_path: Path, make_doc: object) -> None:
    corpus = _repo(tmp_path, make_doc)

    # The model suggests "durable" (in every document: corpus-glue), a term
    # from ADR-002's body ("secrets"), and a word the corpus never uses.
    class _StaticExpander:
        def expand(self, query: str) -> list[str]:
            return ["durable", "secrets", "unheardof"]

    searcher = RetrievalSearcher(build_index(load_corpus(corpus)))
    response = searcher.search("queue", k=2, expander=_StaticExpander())
    assert response.expansion_skipped is False
    # Candidates are tokenized like everything else: "secrets" enters the
    # corpus's normalized form "secret" and survives the filter.
    assert "secret" in response.expanded_terms
    assert "unheardof" in response.rejected_terms
    assert "durable" in response.rejected_terms
    # The corpus-approved expansion term pulled the vault ADR into the hits.
    assert {r.doc_id for r in response.results} == {"ADR-001", "ADR-002"}
    vault = next(r for r in response.results if r.doc_id == "ADR-002")
    assert "secret" in vault.matched_terms


def test_expansion_call_is_async_driven_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    """expand() drives the governed async call itself; no loop may leak."""
    gateway = _install(monkeypatch, _completion("[]"))
    asyncio.set_event_loop(None)
    _expander().expand("q")
    assert len(gateway.calls) == 1
