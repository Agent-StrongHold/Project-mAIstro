"""LLM query expansion: transport discipline and corpus oversight.

Two contracts: the expander *raises* on failure (a silently-empty
expansion would disguise an outage as "the model found nothing"), and
the searcher treats expansion output as *candidates* that corpus
statistics can still veto. The HTTP seam is faked at `sync_client`, the
same seam the linker tests use, so no test touches a network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro_registry.retrieval import (
    ExpansionError,
    NoExpansion,
    OpenAICompatExpander,
    RetrievalSearcher,
    build_index,
    load_corpus,
)
from maistro_registry.retrieval import expand as expand_module


class _Response:
    status_code = 200

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _ExplodingResponse:
    status_code = 500

    def raise_for_status(self) -> None:
        import httpx

        raise httpx.HTTPStatusError(
            "boom", request=httpx.Request("POST", "http://x"), response=httpx.Response(500)
        )

    def json(self) -> Any:  # pragma: no cover - raise_for_status fires first
        return {}


class _Client:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.posts: list[tuple[str, dict[str, Any], dict[str, str]]] = []

    def __enter__(self) -> _Client:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def post(self, url: str, json: dict[str, Any], headers: dict[str, str]) -> _Response:
        self.posts.append((url, json, headers))
        return self.response  # type: ignore[return-value]


def _completion(text: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": text}}]}


def _install(monkeypatch: pytest.MonkeyPatch, response: Any) -> _Client:
    client = _Client(response)
    monkeypatch.setattr(expand_module, "sync_client", lambda **kwargs: client)
    return client


def _expander() -> OpenAICompatExpander:
    return OpenAICompatExpander(base_url="http://llm.test/v1", model="test-model", api_key="k")


def test_expander_posts_openai_compat_payload_and_parses_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install(monkeypatch, _Response(_completion('["queue recovery", "TaskRecord"]')))
    terms = _expander().expand("task queue restart")
    assert terms == ["queue recovery", "TaskRecord"]
    url, payload, headers = client.posts[0]
    assert url == "http://llm.test/v1/chat/completions"
    assert payload["model"] == "test-model"
    assert payload["temperature"] == 0
    assert headers["Authorization"] == "Bearer k"


def test_expander_tolerates_fenced_array(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _Response(_completion('```json\n["a term"]\n```')))
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
    _install(monkeypatch, _Response(payload))
    with pytest.raises(ExpansionError):
        _expander().expand("q")


def test_expander_raises_on_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _ExplodingResponse())
    with pytest.raises(ExpansionError, match="expansion request failed"):
        _expander().expand("q")


def test_expander_requires_base_url_and_model() -> None:
    with pytest.raises(ValueError, match="base_url"):
        OpenAICompatExpander(base_url="", model="m")
    with pytest.raises(ValueError, match="model"):
        OpenAICompatExpander(base_url="http://x", model="")


def test_api_key_defaults_to_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAISTRO_EXPAND_API_KEY", "env-key")
    client = _install(monkeypatch, _Response(_completion("[]")))
    OpenAICompatExpander(base_url="http://llm.test", model="m").expand("q")
    assert client.posts[0][2]["Authorization"] == "Bearer env-key"


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
    import httpx

    def _explode(**kwargs: Any) -> _Client:
        def _raise(*a: Any, **k: Any) -> _Response:
            raise httpx.ConnectError("down")

        client = _Client(_Response({}))
        client.post = _raise  # type: ignore[method-assign]
        return client

    monkeypatch.setattr(expand_module, "sync_client", lambda **kwargs: _explode())
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
