---
inventory-delta:
  packages/maistro-core/tests: +19
---
# PR 1362: mixed-codec quota and real approval conformance

After preserving incoming coverage commit
`ea697ca4bd9c3cf7ca3b87b94036ee0f668e4bb1` and separately recording its measured
+52 cases, the inventory script measured 12,281 -> 12,300 core node IDs. The
**+19** above belongs only to this residual repair. Duplicate PM, context and
scope coverage from our unpublished proposal was omitted; no incoming test
or behavioral assertion was removed.

- `persistence/test_capability_approval_conformance.py`: **15** cases. Five
  real-store behaviors run against file-backed SQLite, standard-codec
  PostgreSQL and production-codec PostgreSQL. Independent connections prove
  effect-identity races, durable lookup and decisions, immutable terminal
  resolution, missing-request rejection and blank-actor rejection. These add
  real persistence evidence alongside the incoming SQL-double tests.
- `quota/test_durable_quota_contract.py`: **4** cases. Budget registration and
  immutable replay, concurrent reservation, terminal usage settlement and
  identical evidence replay run with a standard writer/production peer and
  with a production writer/standard peer. All three stored JSONB columns must
  contain objects. Holds, rounded monetary spend and exactly-once request
  accounting are read from the actual database.

Both modules are included in the existing live-PostgreSQL coverage producer.
Each PostgreSQL case owns a generated schema and two independent real pools;
SQL persistence is not mocked. A missing server skips local PG cases, while
an explicitly required server or missing driver with a configured DSN fails.

The three text-to-JSONB casts repair new quota writes only. Existing
double-encoded JSONB evidence is not migrated and its historical replay
limitation remains; no recursive decoder or silent migration is introduced.
No provider-enforced usage estimate is supplied, and #1196's numeric-budget
usability gap remains open.

Local: five new SQLite cases pass, 14 new PostgreSQL cases skip because local
socket startup is denied. The combined affected suites report 2,847 passed
and 326 skipped. Live PostgreSQL proof must come from CI; skips are not proof.
Quality floors, authorizations and existing ledger entries remain unchanged.
