"""The registry walk: which files are records, and which ids they declare.

Single authority for both questions (#814):

- *Which files are registry records* is decided by `walk_repo` — the same
  pattern set, template skip, and navigation-aid skip the CLI has always
  applied (`docs/adr/ADR-*.md`, `docs/specs/**/*.md`, minus `-template.md`
  files and index/readme docs).
- *Which ids exist* is decided by `declared_ids` — the `id` of every front
  matter that survives `validate_file`. ADR-031 fixes identity in front
  matter (`id: ADR-NNN | SPEC-NNN`); a filename is presentation/storage
  metadata and can never declare an id the front matter withholds.

The CLI and `FilesystemResolver` both consume this module so reference
resolution cannot fork into a second, filename-based identity authority
alongside the registry's declared ids (#814 stop condition).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from maistro_registry.validator import ValidationResult, validate_file

# Walked file patterns. Order is for determinism, not precedence.
WALK_PATTERNS: tuple[str, ...] = (
    "docs/adr/ADR-*.md",
    "docs/specs/**/*.md",
)


def walk_repo(root: Path) -> Iterable[Path]:
    """Yield the registry-record files under `root` (same rules as the CLI)."""
    seen: set[Path] = set()
    for pattern in WALK_PATTERNS:
        for p in root.glob(pattern):
            # Skip scaffolding templates (e.g. ADR-000-template.md): they carry
            # placeholder ids/dates by design and are not real registry records.
            # Match the "-template.md" suffix precisely — a substring check on
            # "template" would wrongly skip real records like
            # ADR-033-templates-and-copier-workflow.md.
            if p.name.endswith("-template.md"):
                continue
            # Skip index/readme docs: they are navigation aids, not registry
            # records (the inventory is derived per ADR-031 §5), so they carry
            # no front-matter by design.
            if p.name in ("README.md", "ADR-INDEX.md"):
                continue
            if p.suffix == ".md" and p.is_file() and p not in seen:
                seen.add(p)
                yield p


def validate_walk(root: Path) -> list[ValidationResult]:
    """Walk `root` and validate every candidate file once."""
    return [validate_file(p) for p in walk_repo(root)]


def declared_ids(results: Iterable[ValidationResult]) -> frozenset[str]:
    """The id index a registry walk produces: ids of *validated* front matter.

    Only front matter that passed `FrontMatter` validation contributes: a
    file with no front-matter block, or whose front matter fails the schema
    (an id that matches no legal pattern, for instance), declares nothing —
    however canonical its filename looks. Every valid record's `repo` is
    `maistro-engine` (the schema's only repository), so this flat set is
    exactly the ids `<repo>#<id>` references may resolve against.
    """
    return frozenset(
        result.front_matter.id for result in results if result.front_matter is not None
    )
