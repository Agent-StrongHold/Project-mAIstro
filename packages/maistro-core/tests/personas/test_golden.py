"""GoldenRecord store tests (SPEC-192 Stage 2, P1)."""

from __future__ import annotations

from datetime import UTC, datetime

from maistro.personas.golden import (
    EvidencedCriterion,
    GoldenRecordStore,
    InMemoryGoldenRecordStore,
    SourceEvidence,
    diff_records,
)


def _source(url: str = "https://example.com/a") -> SourceEvidence:
    return SourceEvidence(url=url, title="t", full_text="x" * 100, fetch_ts=datetime.now(UTC))


def _criterion(name: str, weight: int = 10) -> EvidencedCriterion:
    return EvidencedCriterion(
        name=name,
        weight=weight,
        check={"op": "keywords_any", "words": [name]},
        evidence=["https://example.com/a"],
    )


def test_store_satisfies_protocol() -> None:
    assert isinstance(InMemoryGoldenRecordStore(), GoldenRecordStore)


async def test_save_versions_and_supersedes() -> None:
    store = InMemoryGoldenRecordStore()
    v1 = await store.save("p", [_source()], [_criterion("a")])
    v2 = await store.save("p", [_source()], [_criterion("a"), _criterion("b")])
    assert (v1.version, v1.supersedes) == (1, None)
    assert (v2.version, v2.supersedes) == (2, 1)
    # never deleted
    assert await store.get_version("p", 1) is v1
    assert await store.get_latest("p") is v2
    assert await store.list_versions("p") == [1, 2]


async def test_missing_persona() -> None:
    store = InMemoryGoldenRecordStore()
    assert await store.get_latest("nope") is None
    assert await store.get_version("nope", 1) is None
    assert await store.list_versions("nope") == []


async def test_diff_surfaces_added_removed_changed() -> None:
    store = InMemoryGoldenRecordStore()
    v1 = await store.save("p", [], [_criterion("keep"), _criterion("drop"), _criterion("tune", 10)])
    v2 = await store.save("p", [], [_criterion("keep"), _criterion("new"), _criterion("tune", 30)])
    diff = diff_records(v1, v2)
    assert diff.added == ["new"]
    assert diff.removed == ["drop"]
    assert diff.changed == ["tune"]
    assert diff.has_changes
    assert (diff.old_version, diff.new_version) == (1, 2)


async def test_diff_against_none_is_all_added() -> None:
    store = InMemoryGoldenRecordStore()
    v1 = await store.save("p", [], [_criterion("a")])
    diff = diff_records(None, v1)
    assert diff.added == ["a"]
    assert diff.old_version is None


async def test_diff_no_changes() -> None:
    store = InMemoryGoldenRecordStore()
    v1 = await store.save("p", [], [_criterion("a")])
    v2 = await store.save("p", [], [_criterion("a")])
    assert diff_records(v1, v2).has_changes is False
