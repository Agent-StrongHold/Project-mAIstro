# Issue #1893 repair — d2d34a50

## Frozen scope

- Assigned writer worktree: `/home/dev/Git/wt/auto-1893`, branch `auto-1893`.
- Exact starting HEAD: `4af05c9cc05d584444f8b0b85ce59070fcc2a2c4`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Process only issue #1893 and supplied job `d2d34a50a1bd476d8cb3e003404c9325`; no GitHub mutations or new work items.
- Candidate implementation files: `packages/maistro-core/src/maistro/tasks/admission_codec.py`, `packages/maistro-core/src/maistro/runs/admission_identity.py`, their existing tests, and this report. A new inventory note is required if tests change. Vulture ledger changes only for reproduced, reviewed findings under the explicit repair exception; no reachability grants or ledger edits.
- Initial worktree clean; no incoming edits to salvage.

## Initial evidence and assumptions

Read complete issue body from supplied dispatch snapshot. Driver logs report dependency sync, ruff check and format passing, codec tests 201 passed / 3 skipped, suite inventory passing (16466 nodes). These are driver evidence, not independently executed acceptance evidence.

The bare CI `test: failure` has no failing node in the prompt. Assumption: reproduce focused tests and inspect supplied check evidence before proposing a repair. Prior reachability authorization failure is an independent suspected blocker, not permission to alter gates or activate this staged codec. No production activation or new execution authority is authorized.

## Results

Reproduced required gate blocker at the exact starting head (1200-second timeout):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 findings / reviewed identities, zero unclassified. No Vulture amendment warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`: FAIL, exit 1. New unauthorized unreachable modules AND dispositions for `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` (169 trusted -> 171 candidate). Logs: `worker-vulture.log`, `worker-provenance.log` in the supplied job directory.
- `git merge-base HEAD 3c761d14db944a727fa0744444bc67cfe36d49f7` confirms the assigned base is incorporated. No sync conflict exists.

Read accepted ADR-081426-1f7c and ADR-082526-7f02: physical execution remains Attempt-owned and admission provenance immutable. No inferred receipt or competing authority is permissible. The codec is explicitly a staged, unwired representation leaf; activating it or changing reachability grants to suppress the failure is outside this assignment. Vulture's narrow exception does not authorize reachability ledger edits.

Fresh `uv run ruff check .`, `uv run ruff format --check .` (3277 files) and targeted `uv run mypy` on both implementation modules all PASS. Complete codec and codec tests inspected, plus adjacent identity constructors/tests. Production-source import search finds only the codec -> identity import and Vulture whitelist import, no runtime consumer.

Read supplied prior result and the captured #1325/#1855/#1945/#2109 PR bodies with their own head qualifiers. #2109 concerns CodeQL alert numbers, not this codec; it is not an additional work item. No supplied failing node/traceback justifies a test repair at this head. Full CI remains UNVERIFIED rather than inferred from earlier reports.

Docker inspection confirms the lane-local `auto-1893-pg` container uses `pgvector/pgvector:pg18`, published only on localhost port 15498. The existing pg_pool fixture registers production JSON codecs and truncates scratch tables, so live tests will use a new disposable job database, never an earlier worker's database.

Additional gates PASS: suite inventory (16466 nodes, no duplicates), shipped-surface truth, candidate reachability (1396 modules, 171 unreachable), dispositions (50 groups), promotion surface (74 tolerated). Candidate-ledger passes do not override the trusted-base failure.

Created disposable database `maistro_1893_d2d34a50` only after verifying it did not exist. First `uv run alembic upgrade head` exited 1 because the localhost connection requires a password (`fe_sendauth: no password supplied`). This is environment setup, not a codec/test regression. The failure is retained in `worker-migrations.log`; retry will use the existing lane container's configured credential without logging or committing it. No test ran in this failed attempt.

## Live PostgreSQL validation

Retry succeeded using the container's existing credential via process environment, without changing database authorization. `uv run alembic upgrade head` migrated the fresh database through the actual chain from empty -> 001 -> ... -> 062. Log: `worker-migrations-retry.log`. No downgrade/schema recreation or earlier database modification.

Executed at starting source SHA with DATABASE_URL, MAISTRO_TEST_PG_DSN and MAISTRO_TEST_DATABASE_URL targeting that same database, MAISTRO_REQUIRE_PG_LEGS=1, REQUIRE_AUTH=false and MAISTRO_DRY_RUN=1:

```text
uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q -o junit_family=legacy --junitxml=/home/dev/maistro/jobs/d2d34a50a1bd476d8cb3e003404c9325/worker-pg-tests.xml
```

**204 collected, 204 passed, 0 failures/errors/skips** (1.46s). Log: `worker-pg-tests.log`; XML contains collected node identities and session properties. Both pools used `maistro_1893_d2d34a50`, server `172.17.0.9/32:5432`; production/raw backend PID pairs: unbound 18406/18407, bound 18408/18409, acknowledged 18410/18411. Each state persisted exactly one admission row. Tests injected escaped lone-surrogate TEXT into each snapshot column and required safe typed failures with preserved headers through both pools.

Independent final SQL counts: task_idempotency=0, canonical_runs=0, canonical_projects=0; alembic revision=062 (`worker-pg-final-counts.log`). Disposable database retained for handoff. These direct storage tests do not prove authorized admission or Run creation.

## Acceptance evidence and limits

| Criterion | Executed evidence / limit |
| --- | --- |
| Frozen/slotted header, shared named-column interfaces, six error codes, header matches scalar fields | Source inspection; header mismatch, scalar, format and missing-column tests pass. |
| UUID .hex storage only, signed timestamps, #1851 immutable constructors, fresh flat mapping | Owner/generation, timestamp, identity, immutability and encode tests pass. |
| Exact v2 snapshots and binding | Three-state round trips pass; independent task_id/receipt_id/run_id shape assertions pass against migration 055 on PostgreSQL. |
| Legacy bound/unbound/partial without invented identity | Bound-with-receipt, unbound, partial pair, receipt-only and bound-pair-without-receipt tests pass. The latter remains partial because #1851 requires receipt evidence; no guessed receipt is permitted. |
| Header preserves expiry/fingerprint despite malformed snapshots or partial bindings | Both named separation tests pass; no clock, incoming fingerprint or claim assessment exists in the codec. Replacement/409 precedence belongs to the future consumer, not this leaf. |
| Unsupported formats fail closed, strict TEXT JSON, duplicate/nonobject/bare nonfinite rejection, safe errors | Relevant rejection tests pass, including nested, numeric-fidelity, Unicode and secret-hygiene cases. |
| Tagged program_context preserved, stored fingerprint unchanged | Tagged nan/inf/-inf tests pass; codec does not materialize tags or recompute fingerprints. |
| Same migrated schema with raw and production JSON codecs | Live paired-pool tests pass with required DSNs, non-None production pool, distinct recorded sessions, TEXT equality, zero residue. |
| Real model evidence encoding/materialization via model_of/model_of_json and original-model fingerprint computation | **UNVERIFIED** by these tests: fixture tags/fingerprints are manually constructed and snapshots are not TaskResponse/Run materializations. |
| Run INSERT yields JSONB object, not double-encoded string | **UNVERIFIED**: codec tests insert no canonical Run. |
| Real authorized principals, Workspace/Project and registered Graph kinds | **UNVERIFIED**: fixture identities are placeholders; constructing DTOs is not authorization or admission. |
| No SQL mutation, HTTP/queue change, live assessor/scope changes, policy or competing execution authority | Complete codec source inspected; only this report changes in this round. Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged. |
| Ruff, format, applicable mypy, inventory and relevant static gates | Fresh commands above pass, except required trusted-base provenance. No test additions or count delta; no new inventory note needed. |
| Runtime reachability and integration readiness | **BLOCKED**: production-source search finds no consumer, and trusted-base gate rejects the new module/disposition rows. Test and whitelist imports are not runtime wiring. |
| Full unchanged required CI and generic reported test failure | **UNVERIFIED**: focused tests pass; no current failing node/traceback supplied. No pre-fix failure or new mutation run claimed. |
| Coordination, activation and parent closeout | Assigned writer/base honored. No policy decision, production activation, closure or integration approval inferred. |

## Final handoff

Changed file: `docs/testing/issue-1893-repair-d2d34a50.md` only. No implementation/test/whitelist/ledger/grant/gate changes; no speculative repair. All Python validation used `uv run`, with 1200-second outer timeouts. `git diff --check` passed.

Required blocker: `quality/reachability-baseline.json:131,147` and `quality/reachability-dispositions.json:612-613`, rejected by `check-ratchet-provenance.py` as enforced in `.github/workflows/vulture-ratchet.yml`. Resolving this requires an already-landed trusted-base authorization under repository policy, or separately authorized real consumer integration; this lane may manufacture neither. The assigned base is already incorporated, so no fetch/merge/conflict repair was indicated. Request the current CI failing command/node/traceback before further test repair.

Progress: checked 1, done 0 source repairs, skipped 0, errors 1 unresolved required gate (initial DB credential setup failure resolved). Next: external prerequisite and current CI traceback. Verdict **BLOCKED**. Commit is a local handoff only; no push or GitHub mutation.
