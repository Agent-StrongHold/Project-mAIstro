# #1893 repair handoff — 76216c88

## Frozen scope and result

- Writer worktree/branch: `/home/dev/Git/wt/auto-1893`, `auto-1893`.
- Starting source SHA: `1a5519bc49dfeaf5c8a79a0d1e2eef409f726d63`.
- Assigned base and resolved local `origin/develop`: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence directory: `/home/dev/maistro/jobs/76216c88662a4436ab604d7030d7e3fa`.
- Snapshot: #1893 only, supplied issue/PR evidence, admission codec/identity source and adjacent tests, relevant quality gates, this handoff. Initially clean; nothing to salvage. No fetch, merge conflict, source/test change, ledger/grant change, gate change or GitHub mutation.
- **BLOCKED**: reproduced the trusted-base reachability failure. Vulture and focused tests pass; no evidence-backed source repair was identified. This report is the only changed file and is committed locally. No test inventory delta.

Read repository instructions, the captured issue body and linked PR bodies, prior result, driver `check-0.log` through `check-4.log`, codec/identity implementation and adjacent tests, quality policy, and accepted ADR-081426-1f7c and ADR-082526-7f02. The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model, Attempt-owned execution identity and immutable admission provenance remain unchanged.

Ambiguity: the repair prompt reports `test: failure` without a current-head failing node or traceback. Assumption: validate the assigned slice and named debt gates; do not change unrelated suites or guess a scanner finding. Full required CI and the reported test failure remain **UNVERIFIED**. The driver’s 201 passed / 3 skipped result was not accepted as PostgreSQL proof.

## Independently executed commands

Each validation subprocess used a 1200-second timeout. Logs below are in the evidence directory.

| Command | Result / log |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323 reviewed identities, 1323 findings, zero unclassified; `worker-vulture.log`. No ledger amendment warranted. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | **FAIL, exit 1**: unauthorized unreachable modules and dispositions; `worker-provenance.log`. |
| `uv run ruff check .` | PASS; `worker-ruff.log`. |
| `uv run ruff format --check .` | PASS, 3277 files; `worker-format.log`. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS, two files; `worker-mypy.log`. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS; `worker-surface.log`. |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger, 1396 modules / 171 unreachable; `worker-reachability.log`. |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger, 50 groups / 171 modules; `worker-dispositions.log`. |
| `uv run python scripts/check-promotion-surface.py` | PASS; `worker-promotion.log`. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | Default environment PASS, 16466 nodes, no duplicates; `worker-inventory-default.log`. An earlier invocation inheriting the forced-PG environment failed with 16483 nodes (+17), `worker-inventory.log`. Collection is environment-sensitive: `test_store_boundary_scope_conformance.py:74-75` conditionally adds the PostgreSQL backend. No baseline/note was altered to bank an environment difference. |

Required workflow `.github/workflows/vulture-ratchet.yml:77` runs the failing provenance gate. It rejects `maistro.runs.admission_identity` and `maistro.tasks.admission_codec`: trusted base 169 unreachable/dispositioned modules, candidate 171. The candidate additions are at `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`. Candidate-ledger consistency does not authorize debt expansion. This round's Vulture exception does not authorize reachability grants.

Production search `rg -n 'admission_codec|admission_identity' packages/*/src` found only the codec's DTO import and a Vulture-whitelist import, not a runtime consumer. `admission_codec.py:51-54` explicitly says the consumer is future work. A fake caller/export would neither satisfy runtime acceptance nor respect the issue's no-activation scope.

## Fresh PostgreSQL evidence

Inspected the existing lane-local `auto-1893-pg` container, confirmed the new database name was absent, and created only disposable database `maistro_1893_76216c88`. Existing databases were not modified. Credentials stayed in process environment, not logs or this report.

`uv run alembic upgrade head` passed on the empty database through the real chain, including migration 055, to revision 062 (`worker-migrations.log`). PostgreSQL version: 18.6. No schema recreation, SQLite substitute or destructive downgrade.

With nonempty `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` targeting that database, plus `MAISTRO_REQUIRE_PG_LEGS=1`, `REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/home/dev/maistro/jobs/76216c88662a4436ab604d7030d7e3fa/worker-pg-tests.xml
```

**204 collected, 204 passed, zero skips**, in 1.51 seconds. `worker-pg-tests.log` and XML record outcomes, node identities and database session properties. Production `pg_pool` was non-None and registered production JSON codecs. Raw and production sessions read the same migrated database/server (`172.17.0.9/32:5432`):

| State | Production PID | Raw PID | Persisted admission rows |
| --- | ---: | ---: | ---: |
| unbound | 19513 | 19514 | 1 |
| bound | 19515 | 19516 | 1 |
| acknowledged | 19517 | 19518 | 1 |

Existing tests inject escaped lone-surrogate storage TEXT into all three snapshot columns and require safe typed errors through both pools. Unit assertions independently check migration-055's `task_id=receipt_id` / paired `run_id` binding shape. Final independent SQL counts: `task_idempotency=0`, `canonical_runs=0`, `canonical_projects=0`; revision 062 (`worker-pg-counts.log`). Database retained for handoff. No pre-fix/mutation execution is claimed in this unchanged-source round.

## Acceptance audit

| Criterion | Evidence / limit |
| --- | --- |
| Frozen/slotted header, exact interfaces and six error codes; named scalar columns and header/row agreement | Source inspection and passing header/schema/format/scalar mismatch tests. |
| Strict storage UUID `.hex`, signed timestamps, #1851 constructors, fresh flat encode mapping | Passing UUID, constructor, timestamp and encode tests. |
| V2 snapshots and unbound/bound/acknowledged records | Passing three-state unit and real migrated-PG round trips; paired binding columns satisfy SQL constraints. |
| Legacy bound/unbound/partial, receipt-only and announced-without-Run; no invented identity | Passing legacy tests. Reconciliation: #1851 binding requires receipt identity, so a bound task/run pair without receipt evidence stays partial rather than fabricating a receipt. |
| Header survives malformed snapshot/partial binding; unknown formats and bad scalars fail closed | Both named header-separation tests and format/header rejection tests pass. No clock or incoming fingerprint parameter. Expiry/409 ordering remains the future consumer's responsibility. |
| Strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection; safe errors and validated scope | Passing rejection, recursion, numeric-fidelity, Unicode, predecoded-value and error-hygiene tests. |
| Tagged nonfinite evidence and stored fingerprint preservation | Passing nan/inf/-inf tag preservation tests. Decoder does not recompute fingerprint or materialize tags. |
| Actual evidence-json serialization, original-model fingerprint computation and model_of/model_of_json materialization | **UNVERIFIED**: fixtures construct tags/fingerprints directly; no real TaskResponse/Run materialization is exercised. |
| Raw and production pools return identical TEXT snapshots | All three real-PG states executed, same server/database and distinct sessions; no skipped legs. |
| Run INSERT uses text-to-JSONB cast and persists an object, not a JSON string | **UNVERIFIED**: codec tests create no canonical Run. |
| Real authorized principals, Workspace/Project and registered Graph kinds | **UNVERIFIED**: direct codec fixtures use placeholder identities, not authorized admission. |
| No SQL mutation, HTTP mapping, queue/assessor/scope utility, claim decision or legacy/deletion policy changes | Codec source reads/returns mappings only. This round changes only this report. |
| Focused tests, ruff, format, applicable mypy and inventory | Executed outcomes above; no added/deleted tests, hence no new inventory note. |
| Full required CI / runtime reachability / independent mergeability | **BLOCKED / UNVERIFIED**: required trusted-base gate fails, production consumer absent, full CI not run. |
| Coordination, activation and parent closeout | Assigned branch/base honored; no activation, integration approval or issue closure claimed. |

## Next action

Owner coordination must supply an independently landed trusted-base prerequisite or separately authorized consumer integration; this lane cannot manufacture either. Supply the current failing `test` command/node/traceback before requesting a test repair. Re-dispatching this unchanged head does not remove the provenance blocker.

Progress: checked 1 issue; done 0 source repairs; skipped 0; errors 1 unresolved required gate. Local commit records this handoff only.
