---
inventory-delta:
  tests/: +5
---
# 813 — recursive ADR walk and the total non-record list

Issue #813: the registry walked `docs/adr/ADR-*.md` non-recursively while specs
walked `docs/specs/**/*.md`, so a decision document escaped validation by
living in a subdirectory or by lacking the `ADR-` prefix, and the exclusion set
was implicit (a non-matching glob plus two ad-hoc filename checks).

`maistro_registry.cli` now walks both trees recursively (`rglob`), and every
exclusion lives in one declared, total list: `NON_RECORD_FILES`, an exact
filename → reason mapping, plus the pre-existing `-template.md` suffix rule.
A newly added Markdown file defaults to walked-and-validated — `lint --strict`
fails on it until it carries front matter — so it cannot silently fall outside
validation. `OUT-OF-SCOPE.md` and `DECISION-BACKLOG.md` are explicitly
dispositioned as non-records there (they record decisions by citing the ADR
whose front matter the registry validates; they are not themselves decision
records). The walk's yield on the current corpus is byte-identical to the old
glob's, so `lint . --strict` still reports 436 clean files.

Tests added to `tests/tools/registry/test_cli.py` (this delta): nested-ADR
discovery (the specs/ADRs asymmetry regression), unprefixed-decision-document
discovery plus loud `--strict` failure, disposition-by-declared-name-not-prefix
(`OUT-OF-SCOPE.md` skipped, `OUT-OF-SCOPE-COPY.md` walked), the declared
non-record contract for both ledgers, and a real-corpus totality check proving
every Markdown file under either walked tree is either validated or explicitly
dispositioned.
