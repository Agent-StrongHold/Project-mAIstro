"""The registry walk: which files are records, and which ids they declare.

Single authority for both questions (#814, #813):

- *Which files are registry records* is decided by `walk_repo` — the
  recursive, total-disposition walk (#813): every Markdown file under
  `docs/adr` or `docs/specs` is a candidate record, however deeply nested and
  however its filename is spelled, unless its exact filename is declared in
  `NON_RECORD_FILES` or it carries the `-template.md` scaffolding suffix.
  Specs were always recursive; ADRs now match them, so a decision document
  cannot escape validation by living in a subdirectory or lacking the `ADR-`
  prefix (#813 AC-1/AC-2/AC-4).
- *Which ids exist* is decided by `declared_ids` — the `id` of every front
  matter that survives `validate_file`. ADR-031 fixes identity in front
  matter (`id: ADR-NNN | SPEC-NNN`); a filename is presentation/storage
  metadata and can never declare an id the front matter withholds.

The CLI and `FilesystemResolver` both consume this module so reference
resolution cannot fork into a second, filename-based identity authority
alongside the registry's declared ids (#814 stop condition).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType

from maistro_registry.validator import ValidationResult, validate_file

#: Walked trees. Every Markdown file under either tree is a candidate registry
#: record, and both are walked recursively (rglob includes the tree root
#: itself): a decision document cannot escape validation by living in a
#: subdirectory, and — unlike the pre-#813 `docs/adr/ADR-*.md` glob — not by
#: lacking the `ADR-` prefix either (#813 AC-1/AC-4).
WALK_TREES: tuple[str, ...] = (
    "docs/adr",
    "docs/specs",
)

#: Scaffolding templates (e.g. ADR-000-template.md) carry placeholder ids/dates
#: by design and are not real registry records. Match the "-template.md" suffix
#: precisely — a substring check on "template" would wrongly skip real records
#: like ADR-033-templates-and-copier-workflow.md.
_TEMPLATE_SUFFIX = "-template.md"

#: The one, total skip list for the walk (#813).
#:
#: A Markdown file under a walked tree is a registry record and is validated
#: unless its exact filename is declared here with a reason. `walk_repo`
#: applies no other filter, so this list is total by construction: a newly
#: added Markdown file defaults to walked-and-validated — and `lint --strict`
#: fails on it until it carries front matter — so it cannot silently fall
#: outside validation (#813 AC-2). Every entry states its disposition, because
#: a bare filename with an undocumented reason is exactly the implicit
#: exclusion set #813 started from.
#:
#: The decision ledgers are dispositioned rather than validated because they
#: *record* decisions without being decision records: each disposition they
#: carry cites the ADR (`←ADR-NNN`) whose own front matter is what the
#: registry validates. Naming them here is a declared contract, not a filename
#: accident — the #813 stop condition forbids hiding a decision-bearing file
#: merely for lacking the `ADR-` prefix, and any new decision-bearing file
#: outside this list is walked.
NON_RECORD_FILES: Mapping[str, str] = MappingProxyType(
    {
        "README.md": (
            "navigation aid, not a record; docs/specs/README.md is itself "
            "generated (scripts/generate-spec-ac-defined-index.py)"
        ),
        "ADR-INDEX.md": (
            "the derived index (ADR-031 §5); the records it summarises carry "
            "their own front matter, audited by scripts/check-adr-index.py"
        ),
        "OUT-OF-SCOPE.md": (
            "settled-dispositions ledger; each disposition cites the ADR that "
            "owns it, and that ADR's front matter is what the registry validates"
        ),
        "DECISION-BACKLOG.md": (
            "historical (2026-05) open-decisions snapshot; live decision "
            "tracking moved to BACKLOG.md / ROADMAP.md / ADR-INDEX.md"
        ),
    }
)


def disposition(path: Path) -> str:
    """Why the walk does or does not validate `path`: 'record', or the reason.

    The single classification `walk_repo` applies, kept separate so tests (and
    readers) can ask why any given file is or is not validated without
    re-deriving the rules from `walk_repo`'s body.
    """
    if path.name.endswith(_TEMPLATE_SUFFIX):
        return "scaffolding template (placeholder ids/dates by design)"
    non_record = NON_RECORD_FILES.get(path.name)
    if non_record is not None:
        return f"declared non-record: {non_record}"
    return "record"


def walk_repo(root: Path) -> Iterable[Path]:
    """Yield the registry-record files under `root` (same rules as the CLI)."""
    seen: set[Path] = set()
    for tree in WALK_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            if disposition(p) == "record":
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
