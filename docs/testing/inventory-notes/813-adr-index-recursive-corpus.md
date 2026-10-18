---
inventory-delta:
  tests/: +3
---
# 813 — the ADR-index gate walks the corpus recursively too

Issue #813 repair round. The merge-queue branch already made the registry walk
recursive behind the declared `NON_RECORD_FILES` disposition list; this round
unifies that contract with #814's `maistro_registry.walk` (single walk authority
shared by CLI and `FilesystemResolver`) and closes the remaining non-recursive
consumer on the same corpus: `scripts/check-adr-index.py` audited
`docs/adr/*.md` only, so a decision record moved into a subdirectory could
drift from — or vanish from — `ADR-INDEX.md` without the gate noticing.

`_front_matter()` and `_adr_path()` now `rglob`, matching the registry's
discovery exactly; the yield on the current corpus is unchanged (437 records,
`walk --strict`/`lint --strict` clean, index audit clean).

Tests added to `tests/test_check_adr_index.py` (this delta), sandboxed on the
real corpus per the file's convention:

- a nested ADR whose front matter disagrees with its index row still fails the
  audit as the disagreement itself (not "no ADR file carries that id");
- a nested ADR missing from the index is a structural failure;
- `--add-missing` discovers and appends a nested ADR's row.

All three were proven to fail against the pre-#813 non-recursive `glob`
mutation of the script before the fix was restored.

Provenance: the discovery probe used during the previous (timed-out) repair
attempt — `docs/adr/nested/ADR-9999-nested-probe.md`, an intentionally
unindexed scratch record — was itself the live demonstration that the walk now
rejects unregistered Markdown; it is preserved outside the tree and replaced by
the automated tests above (an unindexed file cannot ship in the corpus).
