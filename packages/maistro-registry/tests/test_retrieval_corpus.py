"""Corpus loading: provenance, versioning, and the KNOWN-GAPS split.

Each test builds the corpus shape that makes its assertion meaningful —
a retrieval unit must carry *where* it came from and *which bytes* it
was built from, or downstream results are unattributable.
"""

from __future__ import annotations

from pathlib import Path

from maistro_registry.retrieval import (
    RetrievalSearcher,
    build_index,
    content_version,
    load_corpus,
)
from maistro_registry.retrieval.index import corpus_fingerprint


def _make_repo(tmp_path: Path, make_doc: object) -> Path:
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-queueing.md",
        "ADR-001",
        "Queueing discipline",
        body="Tasks queue for work.",
    )
    make_doc(
        tmp_path,
        "docs/specs",
        "SPEC-002-export.md",
        "SPEC-002",
        "Export pipeline",
        kind="spec",
        layer="Tools",
        status="Implemented",
        body="## Acceptance criteria\n\nExport produces bytes.",
    )
    # Skipped by the same rules as the registry walk.
    (tmp_path / "docs/adr/ADR-000-template.md").write_text("# template\n", encoding="utf-8")
    (tmp_path / "docs/specs/README.md").write_text("# nav\n", encoding="utf-8")
    return tmp_path


def test_corpus_documents_carry_full_provenance(tmp_path: Path, make_doc: object) -> None:
    load_corpus(tmp_path)  # smoke: empty corpus loads without KNOWN-GAPS.md
    repo = _make_repo(tmp_path, make_doc)
    docs = load_corpus(repo)
    by_id = {d.doc_id: d for d in docs}

    adr = by_id["ADR-001"]
    assert adr.kind == "adr"
    assert adr.status == "Accepted"
    assert adr.layer == "Foundation"
    assert adr.path == "docs/adr/ADR-001-queueing.md"
    assert adr.title == "ADR-001: Queueing discipline"
    assert adr.section is None
    # Version pins the exact bytes: stable across loads, sensitive to edits.
    text = (repo / "docs/adr/ADR-001-queueing.md").read_text(encoding="utf-8")
    assert adr.version == content_version(text)
    assert adr.front_matter is not None and adr.front_matter.id == "ADR-001"


def test_renamed_source_keeps_stable_id_but_moves_the_fingerprint(
    tmp_path: Path,
    make_doc: object,
) -> None:
    """Identity lives in validated front matter, location in the path.

    Renaming the file must not re-address the document (the id is the
    registry's, not the filename's), must not fake a content change (the
    bytes are untouched, so the version is too), and must still move the
    corpus fingerprint — the index knows the corpus state changed.
    """
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-queueing.md",
        "ADR-001",
        "Queueing discipline",
        body="Tasks queue for work.",
    )
    before = load_corpus(tmp_path)
    assert [d.doc_id for d in before] == ["ADR-001"]

    (tmp_path / "docs/adr/ADR-001-queueing.md").rename(tmp_path / "docs/adr/ADR-001-discipline.md")
    after = load_corpus(tmp_path)
    assert [d.doc_id for d in after] == ["ADR-001"], "stable id survives the rename"
    assert after[0].path == "docs/adr/ADR-001-discipline.md"
    assert after[0].version == before[0].version, "identical bytes, identical version"
    assert corpus_fingerprint(after) != corpus_fingerprint(before), (
        "the index must see the moved path as a corpus change"
    )


def test_superseded_decision_is_retrieved_with_its_status(
    tmp_path: Path,
    make_doc: object,
) -> None:
    """Historical material is findable, and never poses as active authority.

    The result record carries the lifecycle status it was indexed with, so
    a consumer quoting the hit can see the decision was superseded —
    provenance is where the status discipline lives, not a caller-side
    afterthought.
    """
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-retries.md",
        "ADR-001",
        "Retry policy",
        status="Superseded",
        body="Retries back off exponentially before giving up.",
    )
    # Three unrelated documents so the topic terms stay below the 0.5
    # df-share ceiling — with fewer documents every term is corpus-glue
    # and the measured rejection would (correctly) reject the query.
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-002-vault.md",
        "ADR-002",
        "Vault of secrets",
        body="Vault prose about keys.",
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
    docs = load_corpus(tmp_path)
    searcher = RetrievalSearcher(build_index(docs))
    response = searcher.search("retry backoff", k=5)
    assert [r.doc_id for r in response.results] == ["ADR-001"]
    # The unseen half of the query is reported as rejected, not swallowed.
    assert "backoff" in response.rejected_terms
    superseded = response.results[0]
    assert superseded.document.document.status == "Superseded"
    assert "[Superseded]" in superseded.render(), (
        "the rendered provenance line must name the superseded status"
    )


def test_duplicate_identity_keeps_both_documents_addressable(
    tmp_path: Path,
    make_doc: object,
) -> None:
    """Two files claiming one registry id must not silently become one.

    The registry validator flags an id collision; retrieval neither hides
    it nor drops a side. Both documents stay in the corpus under their own
    paths and content versions, and a search returns both so the caller
    sees the ambiguity instead of an authoritative-looking single answer.
    """
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-queueing.md",
        "ADR-001",
        "Queueing discipline",
        body="Tasks queue for durable work.",
    )
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-001-queueing-v2.md",
        "ADR-001",
        "Queueing discipline, revisited",
        body="Tasks queue for durable work, with leases.",
    )
    # Three unrelated documents so the claimants' shared vocabulary sits at
    # 2/5 = 0.4, below the df-share ceiling that (correctly) rejects glue
    # terms in a tiny corpus.
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-002-vault.md",
        "ADR-002",
        "Vault of secrets",
        body="Vault prose about keys.",
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
    docs = load_corpus(tmp_path)
    assert len(docs) == 5
    claimants = {d.path for d in docs if d.doc_id == "ADR-001"}
    assert claimants == {
        "docs/adr/ADR-001-queueing.md",
        "docs/adr/ADR-001-queueing-v2.md",
    }
    assert len({d.version for d in docs if d.doc_id == "ADR-001"}) == 2, (
        "distinct bytes, distinct versions"
    )

    searcher = RetrievalSearcher(build_index(docs))
    response = searcher.search("durable", k=10)
    assert {r.path for r in response.results} == claimants, (
        "the collision surfaces as two provenance-distinct hits, not one"
    )


def test_version_changes_when_bytes_change(tmp_path: Path, make_doc: object) -> None:
    repo = _make_repo(tmp_path, make_doc)
    before = {d.doc_id: d.version for d in load_corpus(repo)}
    path = repo / "docs/adr/ADR-001-queueing.md"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nAn appended sentence.\n",
        encoding="utf-8",
    )
    after = {d.doc_id: d.version for d in load_corpus(repo)}
    assert before["ADR-001"] != after["ADR-001"]
    assert before["SPEC-002"] == after["SPEC-002"]


def test_known_gaps_is_split_into_section_documents(tmp_path: Path, make_doc: object) -> None:
    repo = _make_repo(tmp_path, make_doc)
    (repo / "KNOWN-GAPS.md").write_text(
        "# Known Gaps\n\nIntro prose.\n\n"
        "### Task queue persistence\n\n"
        "The queue does not recover.\n\n"
        "### Canvas background job runner\n\n"
        "Jobs do not advance.\n",
        encoding="utf-8",
    )
    gaps = [d for d in load_corpus(repo) if d.kind == "known-gap"]
    # Intro plus two sections. The intro has no anchor and keeps the file id.
    assert [g.doc_id for g in gaps] == [
        "KNOWN-GAPS",
        "KNOWN-GAPS#task-queue-persistence",
        "KNOWN-GAPS#canvas-background-job-runner",
    ]
    assert gaps[1].title == "Task queue persistence"
    assert "does not recover" in gaps[1].body
    assert "Jobs do not advance" not in gaps[1].body
    # All sections share the file's content version — one file, one state.
    assert len({g.version for g in gaps}) == 1
    assert gaps[1].path == "KNOWN-GAPS.md"


def test_missing_known_gaps_is_not_an_error(tmp_path: Path, make_doc: object) -> None:
    _make_repo(tmp_path, make_doc)
    assert not [d for d in load_corpus(tmp_path) if d.kind == "known-gap"]


def test_broken_front_matter_degrades_to_body_only(tmp_path: Path, make_doc: object) -> None:
    _make_repo(tmp_path, make_doc)
    # id violates the registry pattern: unindexable as front matter, still
    # retrievable by body — one bad file must not darken the corpus.
    make_doc(
        tmp_path,
        "docs/adr",
        "ADR-999-broken.md",
        "not-a-valid-id",
        "Broken on purpose",
        body="still searchable prose",
    )
    broken = next(d for d in load_corpus(tmp_path) if d.path.endswith("ADR-999-broken.md"))
    assert broken.front_matter is None
    assert broken.doc_id == "ADR-999-broken"
    assert broken.status is None
    assert "searchable" in broken.body


def test_empty_front_matter_block_degrades_to_body_only(tmp_path: Path) -> None:
    """A file whose front-matter block is EMPTY has nothing to validate —
    the same body-only degradation as a broken block, via the other leg."""
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "docs/adr/ADR-060-empty.md").write_text(
        "---\n---\n\n# Empty on purpose\n\nstill searchable prose\n",
        encoding="utf-8",
    )
    doc = next(d for d in load_corpus(tmp_path) if d.path.endswith("ADR-060-empty.md"))
    assert doc.front_matter is None
    assert doc.doc_id == "ADR-060-empty"
    assert doc.title == "Empty on purpose"


def test_known_gaps_without_sections_is_one_document(tmp_path: Path, make_doc: object) -> None:
    """A KNOWN-GAPS.md with no `### ` headings cannot be split — the whole
    file stays retrievable as the single unit the file id names."""
    _make_repo(tmp_path, make_doc)
    (tmp_path / "KNOWN-GAPS.md").write_text(
        "# Known Gaps\n\nEverything works; nothing is known broken.\n",
        encoding="utf-8",
    )
    gaps = [d for d in load_corpus(tmp_path) if d.kind == "known-gap"]
    assert [g.doc_id for g in gaps] == ["KNOWN-GAPS"]
    assert "nothing is known broken" in gaps[0].body


def test_known_gaps_starting_with_a_section_has_no_intro_document(
    tmp_path: Path, make_doc: object
) -> None:
    """Sections from the first line: no intro unit is invented for them."""
    _make_repo(tmp_path, make_doc)
    (tmp_path / "KNOWN-GAPS.md").write_text(
        "### Task queue persistence\n\nThe queue does not recover.\n",
        encoding="utf-8",
    )
    gaps = [d for d in load_corpus(tmp_path) if d.kind == "known-gap"]
    assert [g.doc_id for g in gaps] == ["KNOWN-GAPS#task-queue-persistence"]


def test_walk_skips_non_markdown_entries(tmp_path: Path, make_doc: object) -> None:
    """The corpus is ADR/spec *markdown*: a stray non-md file and a
    directory that merely looks like a document are not corpus."""
    _make_repo(tmp_path, make_doc)
    (tmp_path / "docs/specs/notes.txt").write_text("not markdown", encoding="utf-8")
    (tmp_path / "docs/adr/ADR-099-dir.md").mkdir()  # a directory named like a doc
    paths = [d.path for d in load_corpus(tmp_path)]
    assert "docs/specs/notes.txt" not in paths
    assert "docs/adr/ADR-099-dir.md" not in paths


def test_known_gaps_inclusion_is_opt_out(tmp_path: Path, make_doc: object) -> None:
    _make_repo(tmp_path, make_doc)
    (tmp_path / "KNOWN-GAPS.md").write_text(
        "### Task queue persistence\n\nThe queue does not recover.\n",
        encoding="utf-8",
    )
    without = load_corpus(tmp_path, include_known_gaps=False)
    assert not [d for d in without if d.kind == "known-gap"]
