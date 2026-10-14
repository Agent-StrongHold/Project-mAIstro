# Issue #1893 repair — c05e013d

## Frozen scope and initial checkpoint

- Assigned worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Starting head: `4379f433cafc98d35650a97a29b201331a2172f5` (confirmed); clean initial tree.
- Frozen base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- One item: #1893 repair. Inspect only its admission codec/identity modules,
  their tests, adjacent tasks/runs contracts, applicable ADRs and CI gates,
  and the supplied dispatch/check logs. Potential edits are limited to an
  evidenced codec/test defect, the explicitly permitted Vulture ledger repair,
  inventory documentation if tests change, and this report.
- Supplied `check-0.log` through `check-4.log` inspected: dependency sync,
  lint, format and inventory pass; focused tests report 324 passed, 3 skipped.
  These logs are driver evidence, not independently executed validation.
- Prior result inspected; it reports a trusted-base provenance blocker and no
  reproduced hosted test failure. Neither claim is assumed true for this run.
- Ambiguity: dispatch says `test: failure` but supplies no failing test node.
  Proceed with focused and adjacent tests and exact named gate commands; do
  not invent a code fix or treat skipped database tests as durability proof.
- Scope reconciliation: the issue forbids activation and reachability grant
  changes. The lane permits only the Vulture per-identity ledger exception.
  A missing reachability authorization cannot be repaired by self-approval.

## Executed results

- Exact prescribed Vulture scan independently passed: 1322 findings, 1322
  reviewed identities, zero unclassified. No ledger amendment is justified.
- `RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py`
  independently exited 1: both admission modules are new unreachable modules
  and new dispositions lacking already-landed authorization (169 -> 171).
  Other provenance wrapper checks passed. Do not rerun this unchanged blocker.
- Codec and all its tests inspected: no production consumer; database tests
  insert synthetic DTO identities, not authorized Runs. They prove TEXT pool
  independence, not admission authorization or Run JSONB materialization.
- Docker is available with PostgreSQL 18 services. A separate disposable DB
  will be used if an existing service permits safe isolated database creation.
  No existing database will be migrated, truncated or dropped.
- Ruff check and format passed (3301 files); scoped mypy passed (2 modules).
- Adjacent tasks/runs tests: 1919 passed, 310 skipped, 5 existing aiosqlite
  closed-loop thread warnings, 49.45s; no assertion failure reproduced.
- Shipped-surface and core suite inventory passed (16543 nodes, no duplicates).
- Read accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-083126-5e62:
  retain canonical lifecycle and immutable admission provenance; generated
  candidate ledgers cannot become authorization. No runtime changes proposed.
- First disposable DB attempt: `uv run alembic upgrade head` failed because
  this invocation used `MAISTRO_DATABASE_URL`, but Alembic requires
  `DATABASE_URL`. No migration occurred; the newly created empty DB was
  dropped. This is a validation invocation error, not a product defect.
  Corrected the environment once; the live check below passed.

## Successful live validation

Executed at the frozen source SHA, with 1800-second command timeouts:

```text
uv run ruff check .
uv run ruff format --check .
uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
RATCHET_BASE_REV=2154f845347c9541016288c760f8da3f5cd2e064 uv run python scripts/check-ratchet-provenance.py
REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/tasks packages/maistro-core/tests/runs -x -q
uv run python scripts/check-shipped-surface-truth.py
uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests
```

Results are recorded above; only provenance failed. An exploratory `rg` also
returned 2 for nonexistent `packages/maistro-core/src/maistro/db*`; the actual
Alembic environment and fixture files were read directly instead.

Created **only** disposable database `issue_1893_c05e013d` on the existing
`maistro-postgres` service, PostgreSQL 18.6. Credentials were obtained from the
local service environment without logging or committing them. Set
`DATABASE_URL`, `MAISTRO_TEST_PG_DSN`, and `MAISTRO_TEST_DATABASE_URL` to the same
nonempty URL for that DB, with `MAISTRO_REQUIRE_PG_LEGS=1`, `REQUIRE_AUTH=false`
and `MAISTRO_DRY_RUN=1`. Executed:

```text
uv run alembic upgrade head
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/extensions/test_cli_lock.py packages/maistro-core/tests/extensions/test_pack_contracts.py -x -q -rs -o junit_family=legacy --junitxml=<temporary-worktree-directory>/focused.xml
```

- Real chain from empty database through **063** passed, including 055.
- **327 collected, 327 passed, 0 skipped**, 1.91s. No fake pool or SQLite
  substitution. JUnit properties read before removal of temporary output.
- Raw/production server identity: `issue_1893_c05e013d`, `172.20.0.2/32`, 5432.
  Distinct production/raw backend PIDs: unbound 371575/371576; bound
  371577/371578; acknowledged 371579/371580.
- Each state observed exactly one persisted admission row. Both pools read
  equal TEXT snapshot bytes and decoded records; surrogate corruption was
  injected into each snapshot column and rejected safely through both pools.
- Final SQL: `alembic_version=063`, `task_idempotency` count **0**,
  `canonical_runs` count **0**. Dropped the disposable DB after validation.
  No migration downgrade or destructive migration-chain tests were run.
- No source change or new test was needed; no fresh pre-fix/mutation failure
  is claimed. Existing assertions independently pin task_id/receipt_id pairing
  rather than relying solely on encode/decode self-agreement.

## Acceptance audit

| Criterion | Evidence and limits |
| --- | --- |
| Exact frozen/slotted header, six error codes, typed DTOs, fresh flat encoder mapping | Required interfaces inspected; header mismatch, scalar validation, immutable DTO and fresh-mapping tests passed. |
| Named storage columns, strict UUID `.hex`, signed timestamps and prerequisite constructors | Missing-column, noncanonical UUID, nil UUID, int64/type and constructor validation tests passed. Live INSERT/readback uses named columns. Physical `request` maps to DTO `request_snapshot`. |
| Safe errors with validated scope and suppressed parsing chains | Invalid scope, malformed JSON, unsafe Unicode/numbers/nesting, token hygiene tests passed; live corrupt TEXT safely rejected. |
| Strict object JSON; tagged arbitrary context retained without changing fingerprint | Duplicate/nonobject/bare-nonfinite and tagged-context tests passed. Original model fingerprint -> evidence-json -> model_of/model_of_json integration remains UNVERIFIED: fixtures construct tags directly. |
| v2 unbound/bound/acknowledged immutable snapshots | All three pure and live two-pool round trips passed, including migration-055 binding shape. |
| Legacy bound/unresolved/partial distinction without invented identity | Bound/unbound, one-sided pair, receipt-only, unreadable evidence and completed_at tests passed. Pair lacking receipt is partial because the prerequisite DTO needs explicit receipt evidence; no inferred receipt is introduced. |
| Minimal valid header survives malformed snapshot/partial binding; unknown formats fail closed | Expiry/fingerprint preservation, mismatch and unknown-format tests passed. Inclusive expiry/409 ordering is the future C consumer's behavior, not proven by B2. |
| Real migrated database; raw vs production JSON codecs | 327 tests passed with enforced PostgreSQL legs; distinct sessions, row counts and same-DB identity recorded above. |
| Authorized principals, Workspace/Project and registered Graph; Run JSONB object | UNVERIFIED. Synthetic codec fixtures do not create or authorize a Run; zero canonical Runs is cleanup evidence, not admission proof. |
| No SQL mutation, HTTP/queue change, clock, live assessor, scope utility or new authority | Source inspected; only representation functions, no runtime activation. Import search across production Python finds only codec -> identity and Vulture whitelist -> identity, not a production consumer. |
| Inventory, focused tests, Ruff/format/mypy, required gates | Passed as recorded except trusted-base provenance. Full required integration CI and the generic hosted `test: failure` remain UNVERIFIED; no failing node supplied or reproduced. |

## Final disposition and handoff

**BLOCKED**, not merge-ready. Evidence:
`quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:606-613` lack trusted-base authorization,
independently rejected by the required provenance gate. Module documentation at
`packages/maistro-core/src/maistro/tasks/admission_codec.py:50-53` agrees with the
production import search: this is an inactive contract, not reachable admission.

Only this report changed. No test additions, so no inventory delta is required.
No source, grant, baseline, gate or production behavior changed. `git diff --check`
passed. The Vulture exception supplies no remedy for reachability provenance;
owner coordination and an independently approved trusted-base resolution (or
separately approved real integration) are required. Do not redispatch the same
unchanged blocker without new authorization or a concrete failing test log.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: owner coordination on trusted-base provenance and hosted failing-node evidence}`.
This local report commit is a handoff only; no push or GitHub mutation.

