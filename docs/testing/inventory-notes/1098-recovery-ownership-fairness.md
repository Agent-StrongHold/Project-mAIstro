---
inventory-delta:
  packages/maistro-core/tests: 0
---
# 1098-recovery-ownership-fairness

Rebased onto the develop tip's `#1275` keyset-cursor shape for the same issue:
the owner/admission-source predicate reaches persistence as a provenance
filter applied before the bounded query limit, and the regression coverage
asserts an owner-scoped `list_by_status` returns only runs admitted by that
owner — oldest-first, before `limit`, across store implementations.

Branch content implementing the superseded durable-column mechanism
(`admission_source` columns, owner indexes, migration `033`, and the
continuation-store owner filter) was dropped in favour of develop's
payload-provenance filtering; the run-level owner filter this note records is
the surviving, develop-compatible intent.

The surviving change adds intra-test assertions only — no collected test
identities are added or removed relative to the develop tip, so the recorded
delta is zero. No root tests were removed by this repair.
