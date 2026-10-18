---
inventory-delta:
  packages/maistro-core/tests: +1
---

# auto-119 — diff-coverage repair: `_json_list` tolerance paths pinned

The CI diff-coverage gate (per file, lines 90% / branches 80%) failed on
`packages/maistro-core/src/maistro/persistence/sqlite_learnings.py`: 89.2% of
37 changed lines, with the three degenerate paths of `_json_list` (lines 508,
511–512, 515) uncovered — legacy NULL, junk text, and a JSON scalar in the
M4-B3 applicability/evidence columns.

`test_applicability_columns_written_outside_the_store_read_back_tolerant`
(packages/maistro-core/tests/persistence/test_sqlite_learnings.py) pins the
mapper's tolerance contract end-to-end: a legacy-shaped table whose
applicability columns predate the NOT NULL DEFAULT '[]' tightening (so
`ensure_schema` correctly leaves them alone), one row holding NULL
`works_when`, junk `avoid_in`, scalar `evidence_run_ids` and a well-formed
`evaluation_ids` control, read back through `list_all`. The tolerant defaults
must be per-column, never a blanket wipe and never a crash. Mutation check:
unguarding `_json_list` (plain `json.loads`, no fallbacks) fails exactly this
test; with the shipped code all 20 tests in the file pass.

No production code changed in this repair — the tolerance was already the
documented contract; it was only unmeasured.
