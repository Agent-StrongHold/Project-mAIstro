---
inventory-delta:
  tests/: +1
---
# 37 — the tombstone purge must honor the CreativeBrief RESTRICT too

One new `tests/migrations` node ID closes #37's installed-base gap for the
second `ON DELETE RESTRICT` foreign key into `canonical_projects`. Revision
`072` (renumbered from the `071` it was written as, past develop's landed
`071_sentinel_decision_integrity`) quarantines orphan Projects and purges
them leaf-first, excluding rows
that own protected history — but its predicate checked only
`canonical_runs.project_id`. `design_creative_briefs.project_id` (revision
`050`) carries the identical `ON DELETE RESTRICT`, so an installed base whose
orphan Project owns a CreativeBrief but never ran anything admits the Project
as a leaf: the RESTRICT violation aborts the whole multi-row DELETE statement
and the entire upgrade transaction with it.

`tests/migrations/test_workspace_tombstones_installed_base.py` builds that
shape on a real PostgreSQL server (upgrade to `070`, insert the orphan rows,
run the ordinary `alembic upgrade head` in a subprocess — the
`test_migration_chain.py` pattern that keeps `alembic/env.py`'s
`fileConfig()` out of the pytest process). It asserts the upgrade completes,
the brief-owning and run-owning orphans stay live with their quarantine
provenance, the disposable leaves still get purged, the orphan Workspace is
tombstoned while the live one is not, and the Project → Workspace fence lands
`NOT VALID` over the surviving rows. Verified to fail against the runs-only
predicate with exactly the named
`design_creative_briefs_project_id_fkey` RESTRICT violation.

No production code outside the `072` migration's purge predicate changed, and
no other suite count moved (`formal/` stays 670: the same-round formal-model
repair provisions canonical Workspaces through the existing
`maistro.testing.postgres.provision_workspace` helper and adds no node IDs).
