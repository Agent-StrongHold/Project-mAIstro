"""Corpus loading with provenance and version retention.

A retrieval result is only trustworthy if it says exactly *what* it was
found in. Every `CorpusDocument` therefore carries its own provenance:
repo-relative path, registry id, kind, lifecycle status, and a content
hash (`version`) over the exact bytes it was built from. Downstream —
search results, quality reports, saved indexes — retains that record
whole, so an answer can always be traced to the document state that
produced it (issue #26: "provenance/version retention").

Corpus shape, mirroring the registry CLI's walk (`cli._walk`):

- `docs/adr/ADR-*.md` and `docs/specs/**/*.md` with front matter
  (templates and index/README navigation aids are skipped by the same
  rules the validator uses), plus
- the root `KNOWN-GAPS.md`, split at `### ` headings into one document
  per known gap. Known gaps are shipped, degraded surface area — exactly
  what an architectural question needs to find — but the file has no
  front matter and would otherwise be one unfindable wall of prose.
  Splitting is the "offline document enrichment" half of issue #26:
  retrieval units are chosen at index time, not at query time.

Unknown-id documents (broken front matter, hand-written files) are
still indexed by body text with `front_matter=None`; retrieval must not
go dark because one file fails validation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from maistro_registry.parser import parse_file
from maistro_registry.schema import FrontMatter

# Same discovery rules as `cli._walk`: order is for determinism, not
# precedence. Kept as data here (rather than imported from the CLI) so the
# retrieval package stays importable without the CLI module.
_WALK_PATTERNS: tuple[str, ...] = (
    "docs/adr/ADR-*.md",
    "docs/specs/**/*.md",
)

_KNOWN_GAPS_FILENAME = "KNOWN-GAPS.md"

# KNOWN-GAPS.md sections are `### <title>`; the prose under one heading up
# to the next is one retrieval unit.
_GAP_HEADING_RE = re.compile(r"^### (.+)$", re.MULTILINE)


@dataclass(frozen=True)
class CorpusDocument:
    """One retrieval unit with full provenance.

    `version` is the first 12 hex chars of the SHA-256 over the exact
    file text the document was parsed from — short enough to print in a
    result line, long enough to pin a corpus state between builds.
    """

    doc_id: str
    title: str
    kind: str
    status: str | None
    layer: str | None
    path: str
    version: str
    body: str
    front_matter: FrontMatter | None
    section: str | None = None

    @property
    def provenance(self) -> str:
        """One-line provenance string: id, status, version, location."""
        status = self.status if self.status is not None else "?"
        return f"{self.doc_id} [{status}] ({self.version}) {self.path}"


def content_version(text: str) -> str:
    """Stable short content hash over a document's exact text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _front_matter_or_none(data: dict[str, Any] | None) -> FrontMatter | None:
    """Validate raw front matter, degrading to None instead of failing.

    A typo'd field in one ADR must not take the whole corpus offline; the
    registry CLI already reports such files through `validate`, so here a
    validation failure means "index it by body only", not "raise".
    """
    if not data:
        return None
    try:
        return FrontMatter.model_validate(data)
    except Exception:  # deliberate: any validation failure degrades to None
        return None


def _title_from_body(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and len(stripped) > 2:
            return stripped[2:].strip()
    return fallback


def _known_gaps_documents(root: Path) -> list[CorpusDocument]:
    """Split KNOWN-GAPS.md into one document per `### ` section."""
    path = root / _KNOWN_GAPS_FILENAME
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    rel_path = path.relative_to(root).as_posix()
    version = content_version(text)

    matches = list(_GAP_HEADING_RE.finditer(text))
    documents: list[CorpusDocument] = []

    def _section_document(title: str, section_text: str, anchor: str | None) -> CorpusDocument:
        doc_id = f"KNOWN-GAPS#{anchor}" if anchor else "KNOWN-GAPS"
        return CorpusDocument(
            doc_id=doc_id,
            title=title,
            kind="known-gap",
            status=None,
            layer=None,
            path=rel_path,
            version=version,
            body=section_text,
            front_matter=None,
            section=anchor,
        )

    if not matches:
        documents.append(_section_document(_KNOWN_GAPS_FILENAME, text, None))
        return documents

    intro = text[: matches[0].start()].strip()
    if intro:
        documents.append(_section_document(_KNOWN_GAPS_FILENAME, intro, None))

    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        title = match.group(1).strip()
        anchor = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        documents.append(_section_document(title, text[start:end], anchor))
    return documents


def load_corpus(root: Path, *, include_known_gaps: bool = True) -> list[CorpusDocument]:
    """Load the architectural corpus under `root`, deterministically ordered.

    Order is by (path, section) so two builds over the same corpus see the
    documents in the same sequence — the index fingerprint and every
    golden-set measurement depend on that.
    """
    root = Path(root)
    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in _WALK_PATTERNS:
        for p in sorted(root.glob(pattern)):
            if p.name.endswith("-template.md"):
                continue
            if p.name in ("README.md", "ADR-INDEX.md"):
                continue
            if p.suffix == ".md" and p.is_file() and p not in seen:
                seen.add(p)
                files.append(p)

    documents: list[CorpusDocument] = []
    for path in files:
        parsed = parse_file(path)
        front_matter = _front_matter_or_none(parsed.front_matter)
        documents.append(
            CorpusDocument(
                # Only *validated* front matter may name the id (a raw `id:`
                # that failed validation is exactly the field that cannot be
                # trusted) — and the same trust rule governs every provenance
                # field: status/layer/kind come from the validated object or
                # not at all. The filename stem keeps such documents
                # addressable, and the body keeps them searchable.
                doc_id=front_matter.id if front_matter is not None else path.stem,
                title=_title_from_body(parsed.body, path.stem),
                kind=front_matter.kind.value if front_matter is not None else "doc",
                status=front_matter.status.value if front_matter is not None else None,
                layer=front_matter.layer.value if front_matter is not None else None,
                path=path.relative_to(root).as_posix(),
                version=content_version(path.read_text(encoding="utf-8")),
                body=parsed.body,
                front_matter=front_matter,
            )
        )
    # Front-matter documents sort by path; known-gap sections (appended
    # below) keep document order instead — sections of one file stay in
    # the order the author wrote them, and the file has one fixed path,
    # so the overall result is still deterministic.
    documents.sort(key=lambda d: (d.path, d.section or ""))

    if include_known_gaps:
        documents.extend(_known_gaps_documents(root))

    return documents
