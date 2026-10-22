---
inventory-delta:
  packages/maistro-core/tests: +6
---
# 118 — CI repair: close the diff-coverage gaps the merge queue flagged

Six new node IDs, all in `packages/maistro-core/tests`, one per gap the
Coverage gate (publish-set floor + diff coverage) reported at
1b89299892bd24c593e37eea8efef7788f3a3830:

- `persistence/test_pg_learnings.py` (+3) — `PgLearningStore.promote_learning`
  had no test at all, so its whole body (the ADR-057 authority gate, the
  scoped `UPDATE ... RETURNING`, the provenance round-trip) was uncovered
  changed surface. Now pinned with the file's FakeConnection doubles: the
  success path asserts the exact SQL predicate
  (`WHERE id = $1 AND org_id = $7 AND status = 'active'`), the
  `SET status = 'promoted', stage = 'repertoire'` ladder ride-along, and the
  verdict args in order; the no-match path returns None; and an
  agent-authority call under `SYSTEM_MANAGED` is denied by
  `require_write_authority` before a single query runs.
- `memory/learnings/test_durable_hybrid.py` (+1) and
  `memory/learnings/test_embeddings.py` (+1) — the two spelled-out
  `promote_learning` delegations on `DurableHybridLearningStore` and
  `HybridLearningStore` forward all seven verdict fields (validated_by,
  evaluator_version, validated_at, validation_run_ids,
  validation_content_hash, org_id) verbatim to the wrapped store, and the
  promoted learning reads back through the wrapper.
- `persistence/test_sqlite_learning_validation.py` (+1) — the defensive
  `row is None` branch after the promotion UPDATE: a row deleted between the
  UPDATE and the re-read (possible on a shared database, impossible on a
  private in-memory one) answers None instead of crashing or fabricating a
  learning. Reached with a connection double whose SELECT cursors lose their
  row; the underlying row really was promoted, so the None means "gone", not
  "no-op".

No production code changed in this repair — the same round upgrades
`multidict` 6.7.1 → 6.9.1 and `werkzeug` 3.1.8 → 3.1.9 in `uv.lock`
(pip-audit advisories with fixed versions) and bumps `proxy-addr` 2.0.7 →
2.0.8 / `source-map-js` 1.2.1 → 1.2.2 in the canvas frontend lockfile
(`npm audit --audit-level=high`), all lockfile-only.
