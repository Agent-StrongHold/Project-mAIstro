---
inventory-delta:
  packages/maistro-core/tests: +41
---

# #952 (M9-B1) — extension install-record persistence

Implements the M9-B1 record layer: publisher identity, package
digest/signature metadata, manifest snapshots, catalog provenance, immutable
installed-version identity, and durable trust evidence
(`packages/maistro-core/src/maistro/extensions/`, read surface
`maistro extensions history|show`).

**+41 `packages/maistro-core/tests/extensions/`** (collect-only verified on
this head):

- `test_install_records.py` (12) — reference-store rules, each naming the
  acceptance criterion it pins: same semantic version + different digest is
  refused (identity conflict, nothing persisted); activation callback never
  runs on tampered bytes / foreign signature / forged manifest / unknown
  publisher; idempotent identical re-record; history retains original
  publisher/digest/manifest/provenance/evidence after later installs and
  catalog churn; per-record catalog provenance queryable from history;
  evidence read back rather than recomputed.
- `test_install_store_conformance.py` (26 collected = 12 rules × {memory,
  sqlite} + 2 sqlite-only) — one suite over both store legs; the sqlite leg
  includes the restart test (fresh connection over the same file reads back
  identical records and evidence) and repeatable `ensure_schema`.
- `test_cli_extensions.py` (3 + 2 negative) — `maistro extensions history`
  and `show` over a seeded durable database: publisher, digest, manifest,
  catalog, snapshot time and trust evidence render; unknown extension/version
  and missing database exit non-zero.

Fail-before evidence: with the conflict raise muted in
`extensions/store.py::resolve_install`, the three same-version/different-digest
tests fail (identity silently shared); with verification skipped, the four
tampered-package tests fail (activation boundary reached). Both mutations were
reverted before commit.

Validation on this head: `pytest packages/maistro-core/tests/extensions`
41 passed; mypy --strict (six package srcs, 803 files) clean;
`ruff check` / `ruff format --check` clean on the touched trees;
`check-reachability.py` (no new unreachable entries — the package is wired
through `maistro.cli`), `check-convergence-matrix.py` (row 68 re-worded
`most`→`some` from the recomputed 12/27 share), `check-durable-table-inventory.py`
(two new `indefinite_by_decision` rows), and the vulture per-identity gate
(1338 reviewed identities ↔ 1338 findings; read/write store seams referenced in
`_vulture_whitelist.py` with #953/#954 rationale) all pass with CI arguments.
