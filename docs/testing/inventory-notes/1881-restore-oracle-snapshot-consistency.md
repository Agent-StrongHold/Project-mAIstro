---
inventory-delta:
  tests/: +17
---
# 1881 — restore-verification oracle made snapshot-consistent and dump-byte-independent

Issue #1881: the weekly restore drill (`deploy/scripts/verify-restore.sh`) verified a
restore by re-running `pg_dump` on the restored database and comparing SHA-256 with a
hash of a *second* plain-text dump `backup.sh` had taken separately. Two independent
defects made that an invalid oracle: the two dumps are unconstrained, so concurrent
writes can make them describe different snapshots; and PostgreSQL ≥ 17 plain output
embeds a random psql restrict key by default, so raw bytes differ even for unchanged
semantic state — on the supported pgvector:pg17 image the old drill fails a perfectly
good restore.

The fix binds the authoritative custom-format archive and its verification evidence to
one exported snapshot (`pg_export_snapshot` + `pg_dump --snapshot`), single-sources the
evidence queries in `deploy/scripts/pg-semantic-oracle.sh`, verifies restored semantics
(schema inventory + exact per-table row counts) with four distinct failure classes
(artifact / restore / semantic / verifier), and keeps pg_dump/psql security defaults
(no `--restrict-key`, no dump rewriting).

## What the tests check

`tests/test_backup_restore_oracle.py` (always on): pins the fix's structure —
single-sourced oracle definitions, snapshot binding in the producer, semantic
comparison in the consumer (schema types recorded via `pg_catalog.format_type`,
so typmods like `vector(1536)` vs `vector(768)` are distinguishable), distinct
failure classes, no `--restrict-key` invocation,
docs no longer claiming the retired "bit-for-bit via pg_dump hash" property. Each
structural property is also asserted to fail against the pre-#1881 scripts, pinned
as fixtures under `tests/fixtures/pre-1881/` (not `git show HEAD:...`: on a
committed checkout that already returns the post-change blob), so the tests cannot
pass vacuously against the replaced behavior.

`tests/test_restore_oracle_characterization.py` (integration, skipped without Docker):
live characterization on the production image (pgvector/pgvector:pg17) in throwaway
containers — (1) unchanged state ⇒ varying plain-dump bytes but stable evidence;
(2) a concurrent write makes two unconstrained dumps disagree while the snapshot-bound
archive + evidence agree and the restore matches the snapshot's counts; (3) the real
`verify-restore.sh` passes end-to-end on artifacts produced by the real oracle library;
(4) semantic loss (dropped table; tampered evidence) is rejected as SEMANTIC FAIL.
Known limits: the oracle proves structure and cardinality, not cell-level content.
