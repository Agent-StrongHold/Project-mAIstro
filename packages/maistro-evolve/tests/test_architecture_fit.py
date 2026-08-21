"""Logic tests for the architecture-fit judge (retrieval + head-to-head).

The LLM is stubbed, so these exercise JSON extraction, related-doc expansion,
and verdict parsing without a gateway.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import maistro_evolve.architecture_fit as af


def _doc(doc_id: str, related: list[str] | None = None) -> af.DocRef:
    return af.DocRef(
        id=doc_id,
        title=f"title {doc_id}",
        kind="adr",
        status="Accepted",
        path=Path("x"),
        related=related or [],
        body=f"body of {doc_id}",
    )


def test_extract_json_variants() -> None:
    assert af._extract_json('```json\n["ADR-1"]\n```') == ["ADR-1"]
    assert af._extract_json('sure thing: {"winner": "A"}') == {"winner": "A"}
    assert af._extract_json("no json at all") is None


def test_select_relevant_pulls_in_related() -> None:
    corpus = [_doc("ADR-1", related=["maistro-engine#ADR-2"]), _doc("ADR-2"), _doc("ADR-3")]

    async def stub(messages, **kw):
        return '["ADR-1"]'

    got = asyncio.run(af.select_relevant("change", corpus, stub))
    assert {d.id for d in got} == {"ADR-1", "ADR-2"}  # primary + its related


def test_select_relevant_handles_non_list() -> None:
    async def stub(messages, **kw):
        return "the model rambled and returned no array"

    assert asyncio.run(af.select_relevant("change", [_doc("ADR-1")], stub)) == []


def test_judge_parses_verdict() -> None:
    async def stub(messages, **kw):
        return '{"winner": "A", "cited": ["ADR-1"], "rationale": "fits ADR-1", "confidence": 0.9}'

    v = asyncio.run(af.judge_architecture_fit("c", "a", "b", [_doc("ADR-1")], stub))
    assert v.winner == "A"
    assert v.cited == ["ADR-1"]
    assert v.confidence == 0.9


def test_judge_handles_unparseable() -> None:
    async def stub(messages, **kw):
        return "no verdict here"

    v = asyncio.run(af.judge_architecture_fit("c", "a", "b", [], stub))
    assert v.winner == "tie"
    assert v.confidence == 0.0
