"""Corpus loading: provenance, versioning, and the KNOWN-GAPS split.

Each test builds the corpus shape that makes its assertion meaningful —
a retrieval unit must carry *where* it came from and *which bytes* it
was built from, or downstream results are unattributable.
"""

from __future__ import annotations

from pathlib import Path

from maistro_registry.retrieval import content_version, load_corpus


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
