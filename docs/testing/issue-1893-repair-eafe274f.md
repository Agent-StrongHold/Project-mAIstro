# Issue 1893 repair — eafe274f

## Frozen scope

- Assigned issue: #1893 only; branch `auto-1893`.
- Verified clean starting HEAD: `789d5a06ddf454ee7d877a5f6c2b8c2d39258516`.
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence snapshot: job `eafe274f83a143599d44815c673fc3d2`, existing
  `dispatch-context.json` and `check-0.log` through `check-4.log` only.
- Code/test inspection scope: admission_codec.py, admission_identity.py,
  test_admission_codec.py, test_root_admission_identity.py; adjacent persistence,
  ADRs and CI definitions only to establish their contracts.
- Permitted repairs: evidence-backed codec/identity/test corrections and reviewed
  Vulture identities if its exact gate reports debt. No reachability ledger,
  authorization, gate, scheduler or production-activation changes.
- Ambiguity: dispatch says `test: failure` without its traceback. Treat this as
  unlocalized until reproduced; previous validation claims are not proof.
- No uncommitted incoming work to salvage. No remote operations planned.

## Results

- Driver logs inspected: dependency sync, Ruff check/format and suite inventory
  passed; focused tests were **201 passed, 3 skipped**. Skips do not prove PG.
- Fresh exact Vulture command:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  passed: 1323 findings match reviewed identities, 0 unclassified. No Vulture
  ledger amendment is warranted.
- Verified local `origin/develop` resolves to the dispatch base. Fresh
  `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python scripts/check-ratchet-provenance.py`
  **failed (exit 1)**: both admission modules are NEW unreachable modules and
  NEW dispositions absent from trusted state, without already-landed
  authorization. All other provenance sub-gates passed.
- This reproduces the previous blocker, rather than relying on its claim.
  The Vulture-specific exception does not authorize reachability ledger edits.
  No code/test/inventory changes at this checkpoint.
- Fresh Ruff check and format check passed (3277 files); mypy on both source
  modules passed. Production import search found only the codec's DTO import
  and the Vulture whitelist import: no reachable runtime consumer.
- Read accepted ADR-081226-a66b, ADR-081626-f383 and ADR-082226-5104. The codec
  is representation only, not Run/Attempt execution or admission authority;
  no second store or authority is introduced. Schema 055 uses physical
  `request` TEXT for the DTO's `request_snapshot` and requires paired bound
  `task_id=receipt_id`/`run_id`; the existing encoder matches this constraint.
- Created fresh job-specific disposable DB `maistro_1893_eafe274f` only after
  checking absence, on verified lane-local `auto-1893-pg` (PostgreSQL 18.6,
  localhost port 15498). No existing DB was modified. `uv run alembic upgrade
  head` passed through the real chain to 062. Both test DSNs and DATABASE_URL
  targeted this one DB; `MAISTRO_REQUIRE_PG_LEGS=1` enforced non-skipped legs.
  Focused codec/identity pytest returned 0. Logs and JUnit evidence:
  `worker-migrations.log`, `worker-pg-tests.log`, `worker-pg-tests.xml` in the
  assigned job directory. Independent final SQL: admission rows=0, Run rows=0.
  Database retained for handoff; no destructive downgrade or schema recreation.

## Focused acceptance evidence

All executions below used the unchanged starting source SHA. Focused command:

```sh
uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py packages/maistro-core/tests/tasks/test_admission_codec.py -x -q -o junit_family=legacy --junitxml=/home/dev/maistro/jobs/eafe274f83a143599d44815c673fc3d2/worker-pg-tests.xml
```

**204 collected, 204 passed, zero skipped** (1.53s). Production/raw backend
PIDs were 20931/20932 (unbound), 20933/20934 (bound), 20935/20936
(acknowledged); all reported `maistro_1893_eafe274f`, `172.17.0.9/32:5432`.
Each state persisted exactly one row and round-tripped through both pools.
Corrupt escaped-surrogate TEXT was injected into each of the three snapshot
columns; each pool produced typed, sanitized failure with preserved header.

| Acceptance | Executed evidence / limitation |
| --- | --- |
| Frozen/slotted header; six typed errors; named columns; exact scalar/header match | Complete source inspected; header mismatch, format, missing-column and immutable-DTO tests passed. |
| Strict UUID .hex at storage; signed timestamps; #1851 constructors | Storage UUID, scalar, identity and record-contract tests passed. Owner token omitted from DTO repr and decoder error messages. |
| Fresh flat encoder; exact snapshot evidence | Fresh-mapping, three-state byte-preservation tests and real PG round trips passed. Independent assertions match migration 055 binding CHECK. |
| Legacy bound/unbound/partial; receipt-only and incomplete binding fail without invented identity | Legacy tests passed, including pair-without-receipt and whitespace-corrupt identities. A pair lacking receipt cannot satisfy the immutable binding constructor without guessing; it remains partial. |
| Header expiry/fingerprint survive snapshot and binding failures | Both named header-separation tests passed; no clock or incoming fingerprint is accepted. C/F2 replacement/409 precedence is not implemented or claimed here. |
| Unknown format fails closed | Unknown-format/header-laundering tests passed; no legacy fallback. |
| Strict TEXT JSON and exception hygiene | Duplicate/nonobject/nonfinite, numeric-loss, nesting, invalid Unicode and safe-error tests passed, including live PG corrupt-TEXT injection. |
| Nonfinite program_context tags and stored fingerprint preserved | Tagged-nonfinite round-trip tests passed; no tag materialization or fingerprint recalculation in codec. |
| Real migrated DB; raw vs production codecs | Fresh chain 001 through 062; both nonempty test DSNs address same DB; pg_pool required; zero skipped PG legs, distinct sessions, final zero admission/Run rows. |
| model_of/model_of_json materialization; original-model fingerprinting; actual Run JSONB object INSERT | **UNVERIFIED** by focused tests: fixtures construct tags manually and do not materialize TaskResponse/Run or persist a Run. |
| Real authorized principals, Workspace/Project and valid registered Graph kinds | **UNVERIFIED**: codec tests insert fixture identities directly; this is representation/storage evidence, not authorization/admission/crash/dispatch proof. |
| No SQL mutation, HTTP/queue/scope/assessment change or competing authority | Complete codec inspected and no source changes made. It only reads mappings/returns DTOs or mappings. Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged. |
| Reachable production behavior and unchanged required CI | **BLOCKED / UNVERIFIED**: no runtime consumer; provenance rejects two unauthorized modules/dispositions. Candidate-ledger passes cannot override trusted-base rejection. |
| Coordination/activation | Assigned branch/base retained; no ownership or policy inferred from captured PR text, no activation or issue closure authorized. |

## Additional fresh checks

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests/runs packages/maistro-core/tests/tasks -x -q --timeout=60`:
  **1918 passed, 310 skipped, 5 warnings** (53.33s). No PG DSNs for this wider
  smoke run; these skips are not durability evidence. Warnings report
  aiosqlite worker threads encountering closed event loops in existing
  `test_sqlite_store.py` cases. No evidence ties them to this codec; not repaired
  speculatively. Log: `worker-adjacent-tests.log` in the assigned job directory.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 16466 nodes, zero duplicate evidence.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-reachability.py`: PASS against candidate ledger
  (1396 modules, 171 unreachable).
- `uv run python scripts/check-reachability-dispositions.py`: PASS against
  candidate ledger (50 groups, 171 modules). These two passes do not authorize
  new debt relative to the trusted base.
- Ruff, mypy and exact Vulture commands/results are recorded above. No tests
  added or removed, so no inventory delta note or ledger amendment is needed.

The captured #1325/#1855/#1945/#2109 PR bodies were inspected with their own
head qualifiers, not treated as instructions or current acceptance. No failing
current `test` node/traceback was supplied in driver logs; the complete CI test
job also covers other packages/frontends, deliberately not changed here.
Generic `test: failure` remains **UNRESOLVED**, not disproved by scoped passes.
An attempted optional ADR filename ending `run-provenance-admission-contract.md`
was not found; skipped (not cited as read). A one-off evidence parser initially
assumed every captured API response was an object; corrected to skip lists.
Neither inspection error altered repository code or gate results.

## Handoff

Only changed file: `docs/testing/issue-1893-repair-eafe274f.md` (this evidence).
No demonstrated source defect warrants a repair in this round. No gate,
quality ledger, grant, whitelist, test, inventory count or runtime activation
was changed. No new mutation/pre-fix test result is claimed.

The blocking entries remain `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. Resolution needs a separately
reviewed, already-landed trusted-base prerequisite under the two-merge policy,
or a separately authorized real consumer integration. This lane cannot grant
itself authorization or wire a fake caller. The base already resolves locally;
there is no unresolved merge conflict to repair. Request an exact current CI
command, failing node and traceback before assigning another speculative repair.

Progress: checked 1 issue, done 0 code repairs, skipped 0 issues, errors 1
required provenance gate. Next: external prerequisite and current CI traceback.
Verdict: **BLOCKED**. Local evidence commit only, not integration approval.
