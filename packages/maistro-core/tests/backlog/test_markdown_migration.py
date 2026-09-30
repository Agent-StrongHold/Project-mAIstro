"""The Markdown migration is lossless (#102).

The cutover's first acceptance bullet — the DB import preserves stable ids,
dependencies, source/provenance, acceptance criteria and open/closed state —
is proven here against the real root ``BACKLOG.md``: the strongest form of
"preserves" is that the database can reproduce the file byte for byte, so
that is the round-trip test. The dependency grammar (all three written
forms), the status-vocabulary mapping, and the idempotency of re-import are
covered on synthetic documents where the real file cannot be mutated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from maistro.backlog.cutover import ROOT_DOCUMENT_ID, import_document
from maistro.backlog.markdown_io import (
    MarkdownBacklogError,
    is_terminal_word,
    parse_dependencies,
    parse_markdown,
    render_document,
    render_item,
    status_to_structured,
    validate_document,
)
from maistro.backlog.model import BacklogItem, BacklogItemStatus, BacklogOrigin
from maistro.backlog.store import InMemoryBacklogStore

REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_BACKLOG = REPO_ROOT / "BACKLOG.md"


def _origin(item, order: int) -> BacklogOrigin:
    return BacklogOrigin(
        document=ROOT_DOCUMENT_ID,
        section=item.section,
        subsection=item.subsection,
        order=order,
        status_word=item.status_word,
        gap_marker=item.gap_marker,
        milestone_text=item.milestone_text,
        header_suffix=item.header_suffix or None,
        body=item.body,
    )


def _items_from(document):
    return {
        item.item_id: BacklogItem(
            workspace_id="w",
            title=item.title,
            created_by="test",
            item_id=item.item_id,
            origin=_origin(item, order),
        )
        for order, item in enumerate(document.items)
    }


# ---------------------------------------------------------------------------
# The real file: losslessness
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not REAL_BACKLOG.exists(), reason="repo checkout")
def test_real_backlog_roundtrips_byte_for_byte() -> None:
    text = REAL_BACKLOG.read_text()
    document = parse_markdown(text)
    assert len(document.items) == 151
    rendered = render_document(document.tokens, _items_from(document))
    assert rendered == text


def test_render_is_deterministic() -> None:
    text = REAL_BACKLOG.read_text()
    document = parse_markdown(text)
    items = _items_from(document)
    assert render_document(document.tokens, items) == render_document(document.tokens, items)


def test_real_backlog_stable_ids_and_vocabulary_are_preserved() -> None:
    document = parse_markdown(REAL_BACKLOG.read_text())
    ids = document.item_ids
    # Spot-check the ids the rest of the repository cites.
    for known in ("engine-001", "engine-002", "conductor-001", "turing-004", "sh-080"):
        assert known in ids
    by_id = {item.item_id: item for item in document.items}
    # The status vocabulary survives verbatim, not flattened.
    assert by_id["engine-001"].status_word == "Implemented"
    assert by_id["engine-002"].status_word == "Proposed"
    assert by_id["engine-012"].gap_marker == "gap-impl"
    # A header-suffix item keeps its suffix on the header line.
    assert by_id["turing-004"].header_suffix.startswith(" — Blocked-by:")
    assert (
        by_id["turing-004"]
        .written_block()
        .startswith("**[turing-004] SelfModel/Mood/Drive ontology registration")
    )


# ---------------------------------------------------------------------------
# Dependencies: the three written forms
# ---------------------------------------------------------------------------


def _doc_with(body: str) -> tuple[dict, set[str]]:
    text = (
        "# Backlog\n\n"
        "**[eng-010] Base — Proposed — M1**\n- base work\n\n"
        "**[eng-011] Sibling one — Proposed — M1**\n- work\n\n"
        "**[eng-012] Sibling two — Proposed — M1**\n- work\n\n"
        f"{body}\n"
    )
    document = parse_markdown(text)
    known = set(document.item_ids)
    return {item.item_id: item for item in document.items}, known


def test_canonical_blocked_by_bullet_parses() -> None:
    items, known = _doc_with("**[eng-020] Dependent — Proposed — M1**\n- Blocked-by: `eng-010`")
    assert parse_dependencies(items["eng-020"], known) == ("eng-010",)


def test_bare_sibling_numbers_resolve_within_the_prefix() -> None:
    items, known = _doc_with(
        "**[eng-013] Release pipeline — Proposed — M2**\n- `pkg/v*` tags. Blocked-by 010/011/012"
    )
    assert parse_dependencies(items["eng-013"], known) == (
        "eng-010",
        "eng-011",
        "eng-012",
    )


def test_depends_on_and_header_suffix_forms_parse() -> None:
    text = (
        "# B\n\n**[eng-030] Base — Proposed**\n- work\n\n"
        "**[eng-031] Dependent — Proposed** — Depends on `[eng-030]`\n- more\n"
    )
    document = parse_markdown(text)
    known = set(document.item_ids)
    by_id = {item.item_id: item for item in document.items}
    assert parse_dependencies(by_id["eng-031"], known) == ("eng-030",)
    # The header-suffix annotation lives on the header line in the written
    # block, not in the body lines.
    assert by_id["eng-031"].header_suffix == " — Depends on `[eng-030]`"


def test_prose_mentions_do_not_invent_dependencies() -> None:
    items, known = _doc_with(
        "**[eng-014] Unrelated — Proposed**\n- See also `[eng-010]` for context"
    )
    assert parse_dependencies(items["eng-014"], known) == ()


def test_unknown_dependency_and_cycles_are_refused() -> None:
    bad_ref = "# B\n\n**[eng-001] A — Proposed**\n- Blocked-by: `eng-999`\n"
    with pytest.raises(MarkdownBacklogError, match="eng-999"):
        validate_document(parse_markdown(bad_ref))
    cycle = (
        "# B\n\n**[eng-001] A — Proposed**\n- Blocked-by: `eng-002`\n\n"
        "**[eng-002] B — Proposed**\n- Blocked-by: `eng-001`\n"
    )
    with pytest.raises(MarkdownBacklogError, match="cycle"):
        validate_document(parse_markdown(cycle))


# ---------------------------------------------------------------------------
# Status vocabulary -> structured open/closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("Proposed", BacklogItemStatus.OPEN),
        ("Accepted", BacklogItemStatus.OPEN),
        ("Accepted (spec)", BacklogItemStatus.OPEN),
        ("Blocked", BacklogItemStatus.BLOCKED),
        ("Implemented", BacklogItemStatus.DONE),
        ("Abandoned", BacklogItemStatus.REJECTED),
        ("Obsolete", BacklogItemStatus.REJECTED),
        ("Superseded", BacklogItemStatus.REJECTED),
    ],
)
def test_status_words_map_onto_structured_state(word, expected) -> None:
    assert status_to_structured(word) is expected
    assert is_terminal_word(word) == expected.is_terminal


def test_duplicate_ids_are_refused() -> None:
    text = "# B\n\n**[eng-001] A — Proposed**\n\n**[eng-001] Again — Proposed**\n"
    with pytest.raises(MarkdownBacklogError, match="duplicate"):
        parse_markdown(text)


# ---------------------------------------------------------------------------
# Import into the store: stable ids, state, idempotency
# ---------------------------------------------------------------------------


async def test_import_preserves_ids_deps_and_terminal_state() -> None:
    store = InMemoryBacklogStore()
    text = (
        "# B\n\n**[eng-001] Base — Implemented — M1**\n- Evidence: done in PR #1\n\n"
        "**[eng-002] Dependent — Proposed; `gap-impl` — M1**\n- Blocked-by: `eng-001`\n"
    )
    document = await import_document(store, text)
    assert document.item_ids == ("eng-001", "eng-002")

    base = await store.get_item("eng-001")
    assert base is not None and base.status is BacklogItemStatus.DONE
    assert base.closure is not None
    assert base.closure.evidence_refs == (f"{ROOT_DOCUMENT_ID}#eng-001",)
    assert base.origin.status_word == "Implemented"
    assert base.origin.milestone_text == "M1"
    # details is the verbatim body, including the blank separator line that
    # belongs to the item's block in the document.
    assert base.details == "- Evidence: done in PR #1\n"

    dependent = await store.get_item("eng-002")
    assert dependent is not None
    assert dependent.status is BacklogItemStatus.OPEN
    assert dependent.dependencies == ("eng-001",)
    assert dependent.origin.gap_marker == "gap-impl"
    assert dependent.origin.order == 1


async def test_reimport_is_a_no_op_when_nothing_changed() -> None:
    store = InMemoryBacklogStore()
    text = "# B\n\n**[eng-001] Base — Proposed — M1**\n- work\n"
    await import_document(store, text)
    first = await store.get_item("eng-001")
    await import_document(store, text)
    second = await store.get_item("eng-001")
    assert second is not None and first is not None
    assert second.version == first.version == 1
    assert len(await store.events("eng-001")) == 1  # only CREATED


async def test_reimport_updates_changed_items_and_transitions_state() -> None:
    store = InMemoryBacklogStore()
    before = "# B\n\n**[eng-001] Base — Proposed — M1**\n- work\n"
    await import_document(store, before)
    assert (await store.get_item("eng-001")).status is BacklogItemStatus.OPEN

    after = "# B\n\n**[eng-001] Base — Implemented — M1**\n- work\n- Evidence: PR #9\n"
    await import_document(store, after)
    item = await store.get_item("eng-001")
    assert item.status is BacklogItemStatus.DONE
    assert item.closure is not None
    assert item.origin.body == ("- work", "- Evidence: PR #9")

    # Back to open: reopen, not a silent overwrite.
    await import_document(store, before)
    reopened = await store.get_item("eng-001")
    assert reopened.status is BacklogItemStatus.OPEN
    assert reopened.closure is None
    kinds = [event.kind.value for event in await store.events("eng-001")]
    assert "closed" in kinds and "reopened" in kinds


async def test_imported_item_exports_byte_identically() -> None:
    from maistro.backlog.cutover import export_document

    store = InMemoryBacklogStore()
    text = "# B\n\n**[eng-001] Base — Proposed — M1**\n- work\n"
    document = await import_document(store, text)
    assert await export_document(store, document) == text


async def test_export_refuses_items_missing_from_the_store() -> None:
    from maistro.backlog.cutover import CutoverError, export_document

    document = parse_markdown("# B\n\n**[eng-001] Base — Proposed**\n")
    with pytest.raises(CutoverError, match="eng-001"):
        await export_document(InMemoryBacklogStore(), document)


def test_render_item_for_database_native_items() -> None:
    item = BacklogItem(
        workspace_id="w",
        title="Native item",
        created_by="agent",
        item_id="eng-900",
        milestone="M4",
        dependencies=("eng-001",),
        details="do the thing",
    )
    rendered = render_item(item)
    assert rendered.splitlines()[0] == "**[eng-900] Native item — Proposed — M4**"
    assert "- Blocked-by: `eng-001`" in rendered
