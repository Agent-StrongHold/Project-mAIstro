# Issue #860 — repair checkpoint (8014ccd8)

## Frozen scope

- Assigned item: #860 only; branch `auto-860`, initial clean HEAD
  `759f4e369bcda1b2c3f624da2362595432763d44`, supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolve locally).
- Evidence: supplied dispatch-context.json, previous result ddc84ca1,
  prior check-3.log from 98a11313. Current job has no check-*.log files.
- Files under review: repository instructions and relevant ADRs;
  `packages/maistro-core/{src/maistro/persistence/pg_learnings.py,tests/persistence/test_pg_learnings.py}`;
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, production rate-limit middleware,
  CI gate definitions and `quality/vulture-baseline.json` only if scanner evidence
  requires an authorized repair. Only this report is currently changed.
- Assumption: this is a writer/CI-repair assignment. Previous BLOCKED status
  is evidence to recheck, not authorization to invent an RC artifact or weaken gates.
- Prior failure: schema fence expected 21 statements but production executed 24.
  Must reproduce before changing tests or production. No remote mutations or
  develop synchronization requested absent an actual sync conflict.

## Results

- Prescribed Vulture command: PASS, 1323 findings / 1323 reviewed identities,
  zero unclassified. No ledger change justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q -rs`: 37 passed, 6 skipped (missing `MAISTRO_TEST_PG_DSN`).
  The historical failure does not reproduce: the independent expected-DDL
  list already includes all three validation audit columns at lines 179–181,
  matching production `_EPISTEMIC_COLUMNS`. No test weakening is warranted.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py
  -x -q -rs`: 74 passed. Combined focused tests: 111 passed, 6 skipped.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites, 31128
  unique test identities, zero duplicate evidence.
- `uv run python scripts/check-deployment-claims.py`: PASS (component existence,
  not deployed behavior).
- `git diff --check`: PASS.
- Commands ran with 600–1200 second timeouts. CI arguments checked in
  `.github/workflows/{quality,vulture-ratchet,ci}.yml`.

## Architecture and acceptance

Read repository instructions, docs/README.md and accepted ADR-085,
ADR-081626-f383 and ADR-082526-b36a. Preserve the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt spine; the Run store remains lease
and fencing authority. The later lease ADR adds renewal/reclaim obligations,
not a waiver of recovery testing. ADR-085's principal identity and the current
middleware's documented process-local budget do not establish #860's stronger
replica-selection non-bypass requirement. Resolve that mismatch explicitly;
do not create an alternate authorization path or relax promotion gates.

| Acceptance criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:152` lists missing users/Workspaces, Graph fan-out, successful model/tool, Design/Canvas and background/Goal work. Driver mix at `run_soak.py:1381` contains health/task/receipt/metrics traffic with one credential. No RC-specific applicability decision supplied. |
| At least two deployed application replicas | **UNVERIFIED**. Boot-contract tests pass; no designated immutable RC deployment was executed. Two ASGI middleware instances are not deployed replicas. |
| Sustained saturation, queues, reclaim, retries and leaks | **UNVERIFIED**. Real child-process sampler regression passes; neither that test nor mocks prove long-window production saturation/reclaim or absence of leaks. |
| No duplicated physical work | **UNVERIFIED**. Receipt/admission tests pass, but `run_soak.py:1044` explicitly cancels the schedule probe's Run without executing it. Admission deduplication does not establish physical-work fencing for tasks/Attempts/Goals. |
| Rate/security/degraded non-bypass | **Contrary production-middleware evidence**: `test_soak_promotion_gates.py:439` passes for both authenticated and unauthenticated identities, showing `[200, 200, 429]` on each replica after exhausting the first. `api/rate_limit.py:93` constructs an independent in-memory limiter; `main.py:648` installs it. Local 429 enforcement and backpressure pass; stronger deployment acceptance remains **UNVERIFIED**. |
| Full telemetry with explicit thresholds | **UNVERIFIED**. Thresholds exist in the profile; `run_soak.py:1410` samples driver loop lag, not application loop lag. No fresh complete production query/lock/pool/worker/queue/error series or threshold adjudication. |
| Kill/restart active work, drain/fencing/recovery | **UNVERIFIED**. Boot cleanup and gate tests pass, not an active-work production recovery experiment. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED**. No designated RC digest/configuration supplied. `run_soak.py:730` fails exact-artifact evidence for its host-process topology; executed synthetic four-hour CLI cases verify rejection, not four hours of traffic. |
| Findings filed/reclassified | Historical schema failure does not reproduce; vulture is clean. Rate-budget mismatch and release-evidence gaps recorded locally. External filing/reclassification **UNVERIFIED**; GitHub mutations forbidden. |
| Machine/human evidence bound to artifact/config hashes | **UNVERIFIED**. This report is validation evidence only, not a fresh hash-bound production soak bundle. |

## Final handoff

Only `docs/testing/soak/issue-860-8014ccd8-repair.md` changes this round.
No code/test/ledger repair is justified by the supplied failure and fresh gate
results. No test addition means no inventory delta. The inherited 464-file
branch diff was preserved and is not certified by these focused checks.

**BLOCKED** on acceptance, not on the historical schema or Vulture gate.
Next: designate immutable RC image/configuration, resolve replica-budget
semantics, complete representative workload/physical-effect/recovery and
application-telemetry oracles, then run the unchanged production artifact for
at least the profile's 14400 seconds. Docker is not claimed unavailable;
a short host preflight cannot substitute for those missing inputs and proof.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands; six database-dependent tests skipped. Local
commit is a writer handoff only, not integration or promotion approval.

## Revalidation checkpoint — job b08ee82ce6474ec28ad10087f513250f

Frozen item remains #860 only, starting at clean `81a9fdd67d689e792be324fb4ecdd986dcd33efc`
with supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7`. This checkpoint
updates the existing report rather than creating another duplicate handoff.
The current job-directory snapshot contains no driver `check-*.log`. Read the
supplied historical `98a11313/check-3.log` and `8014ccd8/result.json` directly:
the former failed on 21 expected versus 24 actual DDL statements; the latter
was blocked on acceptance, not a develop-sync conflict. No merge was needed.

Fresh executed validation (1200-second command timeouts):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  exit 0, 1323 reviewed identities / 1323 findings, zero unclassified. No
  retained identity needs banking and no ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **111 passed, 6 skipped**, 2.68 seconds. Skips explicitly require
  `MAISTRO_TEST_PG_DSN`; no live PostgreSQL result is claimed. The historical
  schema-fence failure does not reproduce. Expected DDL independently lists
  the three audit columns at `test_pg_learnings.py:179–181`, matching production.
- `uv run ruff check .`: exit 0.
- `uv run ruff format --check .`: exit 0, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: exit 0, 17 suites,
  31128 unique identities, zero duplicate evidence.
- `uv run python scripts/check-deployment-claims.py`: exit 0; this checks
  component existence, not a live deployment.

Logs reside in `/home/dev/maistro/jobs/b08ee82ce6474ec28ad10087f513250f/worker-*.log`.
Read repository instructions, documentation authority hierarchy, accepted
ADR-085, ADR-081626-f383 and ADR-082526-b36a. Their reconciliation remains:
canonical Run-store lease authority and executor renewal/reclaim must be
observed; admission counts cannot substitute for physical execution fencing.
ADR-085 establishes principal identity, not a waiver of the issue's stronger
replica-selection requirement. No competing scheduler or authorization path
was introduced.

All ten acceptance dispositions in the table above remain unchanged after
fresh code inspection and execution:

1. **Representative RC profile — UNVERIFIED:** the current profile expressly
   lacks concurrent users/Workspaces, Graph fan-out, successful tools/models,
   Design/Canvas and Goal/background work (`m3a-load-profile.md:152`).
2. **Two deployed RC replicas — UNVERIFIED:** middleware instances and boot
   tests are not an execution of a designated immutable production deployment.
3. **Sustained saturation/reclaim/retry/leak observation — UNVERIFIED:** these
   fast focused checks are not sustained traffic.
4. **Physical-work uniqueness — UNVERIFIED:** `run_soak.py:1044` cancels the
   admission probe's queued Run without executing it.
5. **Rate/security/degraded non-bypass — not proven:** executed
   `test_replica_selection_has_an_independent_production_allowance` for both
   authenticated and unauthenticated identities observes `[200, 200, 429]`
   independently on each production middleware instance. Local enforcement is
   proven, cluster-wide non-bypass is not. `api/rate_limit.py:93` constructs
   each independent in-memory limiter.
6. **Complete production telemetry and thresholds — UNVERIFIED:**
   `run_soak.py:1410` measures the driver's loop lag, not application loop lag;
   no new production pool/lock/query/worker/queue time series was collected.
7. **Active-work restart/drain/fencing/recovery — UNVERIFIED:** passing boot
   and gate tests do not establish recovery of real physical work.
8. **Long unchanged exact-RC soak — BLOCKED / UNVERIFIED:** no immutable RC
   identity/configuration supplied; `run_soak.py:730` deliberately rejects its
   host topology as exact-artifact evidence. No four-hour run was performed.
9. **Findings disposition — locally recorded; external reclassification
   UNVERIFIED:** GitHub mutations are prohibited. No new failing static gate
   was found to repair.
10. **Hash-bound machine/human RC evidence — UNVERIFIED:** these validation
    logs and this checkpoint are not a production soak bundle.

Only this existing report changes. No tests added; no inventory delta needed.
No speculative code, ledger, grant or gate changes. **BLOCKED** remains the
verdict. Repeating the historical schema/Vulture repair dispatch cannot supply
missing RC evidence: the next actionable input is a designated immutable RC
image/configuration plus resolution of the workload and replica-budget contract,
followed by production physical-effect/recovery oracles and a >=14400-second
unchanged-artifact soak. Docker availability is not asserted either way.
Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues,
errors 0 validation commands; 6 database-dependent test cases skipped.
