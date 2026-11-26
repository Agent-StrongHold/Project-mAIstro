# Issue #1893 repair — job 0014b98a

## Frozen scope and starting evidence

- Assigned worktree: `/home/dev/Git/wt/auto-1893`; branch `auto-1893`.
- Starting head: `b0836530bd62ac4dc277ce01737fb1770e73f589`.
- Assigned develop base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- One item only: repair #1893, specifically the reported `test: failure` and
  exact-debt-ledger checks. No GitHub mutations or activation authorized.
- Working tree initially clean; no incoming work to salvage.
- Frozen file scope: existing admission codec/identity implementations and their
  two adjacent test files, existing B2 inventory notes, relevant ADRs/workflows,
  and this handoff. Vulture ledger may change only for observed retained debt;
  no reachability/grant/gate edits are permitted.
- Read the captured issue body in `dispatch-context.json`, the supplied prior
  result, and all five driver `check-*.log` files. Driver results: dependency
  sync, ruff, formatting and inventory passed; focused tests 201 passed,
  3 skipped. These skips are not PostgreSQL acceptance evidence.
- Ambiguity: the dispatch labels CI `test: failure` but provides no failing
  traceback in the deterministic logs. Proceed by reproducing focused tests
  and named gates; do not guess a code fix.
- Prior provenance failure is evidence to recheck, not assumed current truth.

## Current status

Freshly reproduced required provenance failure (exit 1) using
`RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`:
`maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are both
NEW unauthorized unreachable modules and NEW unauthorized dispositions
(169 trusted -> 171 candidate). The prescribed Vulture command passed with
1323 reviewed findings and zero unclassified; no Vulture amendment is justified.
The exact base resolves and is the merge-base with HEAD; there is no sync
conflict at the assigned snapshot. No runtime, test, ledger, authorization or
policy change has been made.

Fresh validation (1200-second command timeout): ruff check passed; ruff
format --check passed (3277 files); mypy on codec and identity modules passed;
focused codec + identity tests collected 204 nodes, 201 passed / 3 skipped
(missing PG variables); suite inventory passed (16466 nodes, no duplicate
evidence); shipped-surface truth passed. Docker is reachable and an existing
lane-local `auto-1893-pg` pgvector/pg18 container exposes port 15498. Plan: use
a new job-specific disposable database, never mutate earlier workers' databases.

Read accepted ADR-081426-1f7c and ADR-082526-7f02, documentation authority map,
codec/identity sources and codec tests. No competing execution authority or
admission policy is allowed. The row codec is intentionally not activated;
header evidence is separate from consumer decisions. Legacy pairs lacking a
receipt cannot satisfy the immutable binding contract without inventing one;
they remain explicit partial failures rather than guessed bindings.

Reachability search over `packages/*/src` finds only the codec importing DTOs
and `_vulture_whitelist.py` importing AdmissionAssessment, not a runtime caller.
Reviewed both complete focused test files and the production-codec pg_pool
fixture. The initial container probe failed because POSTGRES_USER was unset
and psql defaulted to OS user root; no database was changed. Use the image's
postgres default when POSTGRES_USER is absent, verify current_user, then create
only the new `maistro_1893_0014b98a` database. An exploratory path
`packages/maistro-core/src/maistro/config.py` did not exist; read the actual
`config/database.py` resolver instead. Migration takes DATABASE_URL, while
focused tests require both MAISTRO_TEST_* variables pointing to that same DB.

## Live PostgreSQL result

Created only the fresh job-specific database `maistro_1893_0014b98a` after
verifying it did not exist. Existing database `maistro_1893_final` was queried
for server identity only, not migrated/truncated. Server PostgreSQL 18.6;
`uv run alembic upgrade head` applied the real chain from empty through **062**
(exit 0). No downgrade test was run; no schema was manually recreated.

Executed at starting source SHA, with DATABASE_URL, MAISTRO_TEST_PG_DSN and
MAISTRO_TEST_DATABASE_URL all naming this new DB on 127.0.0.1:15498, plus
MAISTRO_REQUIRE_PG_LEGS=1, REQUIRE_AUTH=false and MAISTRO_DRY_RUN=1:

```
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/tmp/issue-1893-0014b98a-pg.xml
```

**204 collected, 204 passed, zero skipped** in 1.51s. Both raw and
production-codec pools saw the same database/address/port:
`maistro_1893_0014b98a`, `172.17.0.9/32`, `5432`.

| State | Production backend PID | Raw backend PID | Persisted admission rows |
| --- | ---: | ---: | ---: |
| unbound | 17494 | 17495 | 1 |
| bound | 17496 | 17497 | 1 |
| acknowledged | 17498 | 17499 | 1 |

Tests compare exact named-column mappings from both pools with encoded DTOs,
including TEXT snapshot evidence and binding columns. They inject escaped
surrogates independently into request/receipt/provenance TEXT columns, assert
safe typed failures through both pools while retaining header evidence, then
restore the snapshot and delete their row. Final independent SQL counts:
task_idempotency=0, canonical_runs=0, canonical_projects=0; alembic revision=062.
The empty migrated job DB is retained for handoff. No prior DB claim was used
as current proof. No new regression/mutation test was added or claimed.

## Acceptance review at this source

All ten prospective codec contracts executed in the focused file, including
the three live PostgreSQL states. This is representation/storage evidence,
not activation or authorized Run admission.

| Criterion | Executed evidence / remaining limit |
| --- | --- |
| Frozen/slotted header; six decode codes; exact header/record/encoder interfaces | Complete source inspection; header mismatch, missing schema, unsupported format, scalar-validation tests passed. |
| Named columns, UUID .hex at storage only, signed timestamps, #1851 constructors | Owner/generation/scalar tests and live SQL mapping round trips passed. |
| Exact immutable v2 snapshots, fresh flat bound-parameter mapping | `test_v2_round_trip_preserves_all_snapshot_bytes` in three states, fresh-mapping test, and live two-pool round trips passed. Independent task_id=receipt_id/paired-column assertions passed. |
| No guessed legacy identity; bound, unbound and partial distinct | Legacy binding, missing-receipt, receipt-only, unreadable/padded-evidence tests passed. completed_at grants no authority. |
| Header/full separation and matching row scalars | Expired-header, expiry/fingerprint preservation on full-decode error, header mismatch tests passed. |
| Unknown formats, corrupt scalars, duplicate/nonobject/bare nonfinite TEXT fail closed | Format/scalar/snapshot tests passed, including lossy numbers, excessive nesting and invalid Unicode. Safe error messages/suppressed parsing chains asserted. |
| Tagged nonfinite program_context retained, no fingerprint recomputation | Tagged nonfinite, exact-number and Unicode tests passed; codec simply carries stored tags/fingerprint. |
| Same migrated disposable DB; raw and production codecs; nonempty DSNs and pg_pool | 204 passed, zero skips under required-PG mode, distinct session PIDs on identical server/DB, one persisted row per state; final admission residue zero. |
| No clock/request-fingerprint input, assessment, SQL mutation, HTTP mapping or queue change | Complete codec source inspection; no implementation edits this round. Consumer expiry/replacement/409 decisions are C/F2, not implemented here. |
| Evidence-json model materialization, original-model fingerprinting, Run JSONB object INSERT | **UNVERIFIED**: fixtures construct stored tag dictionaries; tests do not materialize TaskResponse/Run or execute Run INSERT. |
| Real explicit principals, authorized Workspace/Project, valid registered Graph admission | **UNVERIFIED**: fixture identity strings and direct row inserts establish storage shape, not authorized admission or transaction/dispatch invariants. |
| Reachable production behavior and independent integration readiness | **BLOCKED**: no production codec consumer; trusted-base reachability/disposition gate fails. No fake caller/export/activation is permitted. |
| Full unchanged required CI and generic reported `test: failure` | **UNVERIFIED**: focused tests pass; full CI was not run. Captured PR #1945 head fcc8b437f209 lists exact-debt-ledger failure with empty output text, not a current-head failing test traceback. |
| Coordination and production policy | Assigned writer/base is explicit; captured #1325/#1855/#1945 descriptions were reviewed with their own head qualifiers, not treated as validation/activation permission. Parent activation choices remain unresolved/outside scope. |

## Complete commands and outcomes

All validation commands use `uv run`, with 1200-second timeouts. Exact source
is the starting head above; the only tree change is this report.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1323 findings, zero unclassified. |
| `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py` | FAIL exit 1; two unauthorized modules plus two dispositions. Other constituent ratchets passed. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 3277 files. |
| `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py packages/maistro-core/src/maistro/runs/admission_identity.py` | PASS. |
| `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -r s` | 201 passed, 3 skipped without PG variables. |
| `uv run alembic upgrade head` | PASS on new disposable DB, empty -> 062. |
| Focused required-PG pytest command above | 204 passed, zero skips. |
| `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests` | PASS; 16466 nodes, zero duplicate evidence. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |
| `uv run python scripts/check-reachability.py` | PASS against candidate ledger; 1396 production modules, 171 unreachable. This does not override trusted-base rejection. |
| `uv run python scripts/check-reachability-dispositions.py` | PASS against candidate ledger; 50 groups, 149 CONNECT / 20 LIBRARY / 2 RETIRE. |
| `git diff --check` | PASS. |

## Blocked handoff

Changed file: `docs/testing/issue-1893-repair-0014b98a.md` only. No source,
tests, inventory count, whitelist, ledger, grant or gate edits. No test addition
means no inventory-delta note is needed. No GitHub mutations or remote refresh.

The required provenance gate's failure is real, not a guessed Vulture defect.
Its blocking candidate entries remain in quality/reachability-baseline.json
and quality/reachability-dispositions.json. The lane's Vulture-only ledger
exception cannot authorize these entries. Resolution requires the integration
owner to arrange an already-landed authorization under the two-merge policy or
a separately authorized runtime integration consistent with the issue's scope.
This worker cannot land either prerequisite or claim activation permission.
Provide the current failing `test` command/node/traceback before requesting a
source repair; no in-scope failure was reproduced, including on real PostgreSQL.

Progress: checked 1 issue; done 0 code repairs; skipped 0 issues; errors 1
required provenance gate; next: external trusted-base prerequisite and actual
CI test failure evidence. **BLOCKED**. Local evidence commit is handoff only,
not integration approval or issue closeout.
