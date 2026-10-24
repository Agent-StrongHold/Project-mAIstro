# Issue #1893 repair checkpoint (adbe665d)

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`, clean starting head
  `1702deffe3a1bb89510584d716bf4dcb4eeed3ff`.
- Supplied develop base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inspect existing admission codec/identity implementation, adjacent tests,
  relevant ADRs, CI workflow and supplied job evidence. No other issue or PR
  will be processed, and no GitHub mutation will be performed.
- Candidate edit files: this report; codec/identity and their existing tests
  only if an actual defect is reproduced; an inventory note if tests change;
  vulture ledger only if the expressly permitted CI repair is evidenced.
  No reachability ledger/grant/gate changes are authorized.

## Initial evidence and assumption

Driver logs in `/home/dev/maistro/jobs/adbe665d94a74d1596aea57051592a36`:
`check-0.log` dependency check passed, `check-1.log` lint passed,
`check-2.log` formatting passed, `check-3.log` 312 passed / 3 skipped,
`check-4.log` core inventory 16541 passed. These are driver results, not
independent verification or live PostgreSQL proof.

Ambiguity: dispatch reports only `test: failure`, without a failing node.
Proceed by executing focused tests and named gates; do not guess a code fix.
Prior provenance findings are allegations to revalidate, not authority to edit
reachability grants. Production activation remains explicitly out of scope.

## Independent gate checkpoint

- `uv sync --locked --extra dev`: PASS.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`: FAIL (exit 1), reproduced at the assigned head. Both admission modules are new unreachable modules and new dispositions without already-landed authorization. Log: `/tmp/1893-adbe-provenance.log`.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1322 reviewed findings, zero unclassified/never-allowlist. Log: `/tmp/1893-adbe-vulture.log`. No ledger amendment is justified.
- Read accepted ADR-081226-a66b (canonical execution hierarchy), ADR-082526-7f02 (immutable admission provenance), ADR-083126-5e62 (trusted-base quality authority). No reconciliation requires changing their decisions. Candidate ledger edits or fake callers cannot resolve the reproduced blocker.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3301 files).
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`: PASS (16541 nodes, no duplicate evidence).

## Database validation plan

Use a newly created disposable database `issue1893_adbe665d` on the confirmed
local `maistro-postgres` PG18 container (port 5433), never an existing database.
Apply the repository Alembic chain, then execute existing focused tests with
both DSNs pointing to it and `MAISTRO_REQUIRE_PG_LEGS=1`. This establishes only
the codec's storage boundary, not admission authorization or production wiring.

## Live database checkpoint

- Created `issue1893_adbe665d` only after verifying it did not exist. Credentials were taken internally from the local container configuration, never printed or committed.
- `uv run alembic upgrade head`: PASS on the empty database, actual chain `001` through `063` (including `055`); log `/tmp/1893-adbe-migrate.log`.
- With `DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, `MAISTRO_TEST_DATABASE_URL` all pointing at that database, `MAISTRO_REQUIRE_PG_LEGS=1 REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/extensions/test_pack_contracts.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -rs --junitxml=/tmp/1893-adbe-focused-pg.xml -o junit_family=legacy`: **315 passed, zero skipped**, 1.82s. Log `/tmp/1893-adbe-focused-pg.log`.
- Actual raw/production session pairs: unbound `264457/264449`, bound `264461/264459`, acknowledged `264463/264462`; each reports the same database/server `issue1893_adbe665d`, `172.20.0.2/32`, port `5432`, and one persisted row. TEXT snapshots matched across both pools and all three surrogate-corruption injections failed safely through each pool.
- A post-test diagnostic query incorrectly named the Run table `runs` and failed with `relation "runs" does not exist`. This was a validation-script mistake after pytest completed successfully, not a test or product failure. No destructive operation followed; correct table names must be confirmed before the final residue query.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: **15468 passed, 1070 skipped, 3 xfailed, 54 warnings**, 232.66s, exit 0; log `/tmp/1893-adbe-core.log`. This separate package-wide invocation had no PG DSNs; its skips are not PostgreSQL evidence. Warnings include aiosqlite event-loop-closed thread exceptions; no repair to unrelated tests is attempted.
- Corrected post-test SQL, after confirming `canonical_runs` in migration 012: PostgreSQL **18.6**, Alembic version **063**, `task_idempotency=0`, `canonical_runs=0`, `canonical_projects=0`. The disposable database is retained for inspection; no shared database was truncated.
- `uv run python scripts/check-reachability.py`: PASS, 1403 modules / 171 unreachable; `uv run python scripts/check-reachability-dispositions.py`: PASS, 50 groups / 171 dispositioned. These candidate-ledger checks do not override the failed trusted-base provenance gate.

## Acceptance audit at starting source SHA

No executable file changed in this round. The focused run executed all existing
315 nodes, including the ten prospective codec contracts and three real PG
state variants. This is representation/storage evidence, not runtime activation.

| Criterion | Executed evidence and boundary |
| --- | --- |
| Frozen/slotted header, exact interfaces, immutable DTOs, fresh flat mapping | Codec/identity source inspected; focused header/identity and fresh-mapping tests pass. |
| Named columns; strict UUID `.hex`; signed timestamps; #1851 constructors; matching header | Passing UUID, scalar-range/type, header-mismatch, v2 identity/window/binding/acknowledgment tests. Real inserts in all three states satisfy migration 055, including task_id = receipt_id when bound. |
| Six typed error codes; safe scope and suppressed unsafe chains | Passing invalid-scope, schema/format, duplicate/nonobject/nonfinite, excessive nesting, lossy number and surrogate tests. Error messages omit injected private values; parsing cause is suppressed. |
| Legacy bound/unbound/partial, receipt-only, announced-without-Run; no inferred identity | Passing bound-pair, neither-set, one-sided pair, missing-receipt, receipt-only, whitespace and completed_at tests. Bound pair without receipt remains partial because the DTO cannot fabricate receipt evidence. |
| Minimal header survives full decoding failure; unknown format fails closed | Passing expiry and fingerprint preservation tests, unsupported format/schema, header mismatch. No clock or incoming fingerprint exists in the codec; consumer expiry/replacement/409 decisions are out of B2 scope and UNVERIFIED. |
| Snapshot bytes/evidence and fingerprint unchanged | All canonical snapshot round-trip, arbitrary nested JSON, Unicode, exact numeric and tagged nan/inf/-inf tests pass; both raw/production pools read identical TEXT. Existing tests inject tags and a stored fingerprint: original-model fingerprint -> evidence encoding -> model_of/model_of_json materialization remains UNVERIFIED as an integrated path. |
| Live migrated PostgreSQL contrast, both DSNs, non-null production pool | PASS: actual chain 001->063; three state variants, separate backend identities and one persisted row each, final zero rows. Migration downgrade tests were not run. |
| Run payload JSONB is an object, not doubly encoded | UNVERIFIED by the codec tests: they insert admission rows, not Run payloads. No Run insertion changed in this round. |
| Explicit authorized principals, Workspace/Project and registered Graph kinds | UNVERIFIED for production admission. Codec fixtures use identity strings and are not authorization proof. |
| No mutation, HTTP/queue/policy/scope changes, assessment or competing authority | Source inspection: codec is a pure mapping/DTO leaf. No executable change this round; canonical Goal -> Graph -> Run -> NodeRun -> Attempt model preserved. |
| Production reachability | Not established: codec lines 50-53 explicitly document inactivity; production import search finds only codec -> identity and Vulture whitelist imports. Tests/exports are not runtime reachability. Activation remains prohibited. |
| Focused/package tests, lint, format, scoped mypy, inventory | PASS as above; no new tests, so no inventory delta needed. No pre-fix/mutation failure claimed because no executable repair was made. |
| Full unchanged required integration CI; vulture/reachability/disposition/promotion gates | Exact Vulture and candidate reachability/dispositions pass; promotion provenance passes inside the wrapper. Trusted-base reachability/disposition provenance FAILS. Full integration CI is UNVERIFIED; the dispatched `test: failure` has no identified failing node and is not reproduced in the changed package. |

## Blocked handoff

Only changed file: `docs/testing/issue-1893-repair-adbe665d.md`.
No source/test/ledger/grant/gate changes were justified by actual failures.

The remaining blocker is `.github/workflows/vulture-ratchet.yml:77`:
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-614` add two inactive modules
without trusted-base authorization. The Vulture-only repair exception cannot
resolve it. Owner-coordinated, already-landed authorization and subsequent
integration (or a separately authorized real consumer) are required; neither
can be invented by this worker. No merge conflict exists and no fetch/merge
was attempted. Repeating unchanged-source validation will not repair this
policy failure.

Residual risks: end-to-end model materialization, production authorization,
Run JSONB storage, consumer decision precedence, runtime reachability and full
integration CI remain unverified. All prior verification claims were treated
as historical rather than fresh proof.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner-coordinated trusted-base authorization and concrete failing CI test log}`.
Validation/reporting complete; issue repair remains BLOCKED. Local commit only;
no push, PR, issue closure or other GitHub mutation.
