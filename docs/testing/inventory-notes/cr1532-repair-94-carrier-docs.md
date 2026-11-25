---
inventory-delta:
  tests/: +0
---

# cr-1532 repair: sweep-count correction 93 -> 94 carrier documents

Repair round against head `6072523bed82`, base `bd96877ed8`. A prior verifier
round measured the corpus retirement as **93** carrier documents; that scan's
regex did not match Markdown blockquote prefixes, which the gate's
`_BODY_STATUS_RE` (metric v2) explicitly supports. This round re-measured
with the checker's own audit and corrects the stated count to **94**.

## Measured with the gate's own parser, not a side regex

`scripts/check-adr-status-language.py::audit()` (the metric-v2 traversal:
recursive `rglob("*.md")`, `ADR-INDEX.md` skipped, front-matter-parsed
documents only, fenced/indented code blocks blanked by
`_outside_fenced_blocks`, blockquote and list prefixes matched) applied to
`docs/adr` + `docs/specs` materialized from base `bd96877ed8`:

- **94 documents** carry exactly one `body-status-line` finding each
  (**94 findings total**; no document carries more than one).
- Split: **67 ADRs, 27 specs**. The earlier "93 (67 ADRs, 26 specs)" recount
  missed `docs/specs/SPEC-200-builders-safety-layer.md`, whose line was
  blockquoted: `> **Status:** Implemented — the builders safety layer shipped
  to `develop` in #107`. The change removes that line too, so the sweep is
  94 documents, not 93.
- At head `6072523bed82` the same audit finds **0** findings and
  `check-adr-status-language.py` exits 0 (`ok: 0 baselined …`).

## What changed in this round

Count wording only, in eight places; no collected test moved
(`inventory-delta: tests/: +0` — the test edit is a docstring count
correction):

- `docs/adr/ADR-092126-a28a-retire-body-status-lines.md` (Context, Decision,
  Negative trade-off: 93 -> 94, with the blockquote miss named)
- `docs/adr/ADR-INDEX.md` (ADR-092126-a28a row)
- `CHANGELOG.md` (`### Changed` entry)
- `scripts/check-adr-status-language.py` (module docstring, both counts)
- `tests/test_check_adr_status_language.py` (corpus-test docstring)
- `docs/testing/inventory-notes/retire-body-status-lines.md` (corpus-test
  description)

Prior verifier notes (`cr1532-verifier-validation-9da2da12.md`,
`cr1532-verifier-validation-535ffb5a.md`) are left untouched as historical
records of rounds that ran the under-matching scan; this note supersedes
their measured count.

## Re-validation at the corrected head

- `uv run pytest tests/test_check_adr_status_language.py
  tests/test_check_adr_status_language_provenance.py -q` — all pass
  (see round log).
- `uv run python scripts/check-adr-status-language.py` — exit 0.
- `uv run ruff check .` / `uv run ruff format --check .` — clean.
