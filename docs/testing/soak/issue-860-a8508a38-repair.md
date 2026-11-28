# Issue #860 — bounded repair a8508a38

## Frozen scope

- Issue: #860 only; no GitHub mutations or integration approval.
- Worktree: `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `7288cf5f5c24306cb3b169ff20573cc1441740f6` (verified; clean).
- Assigned base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inputs: supplied dispatch-context.json and prior result 8d4b8b4d;
  historical failed check `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
- Inspection/validation surfaces: repository instructions, relevant ADRs,
  `scripts/soak/`, `tests/test_soak_promotion_gates.py`,
  production rate limiting (initial schema-fence path candidate
  `tests/test_soak_schema_fence.py` was not found and skipped; the actual
  reported regression is `packages/maistro-core/tests/persistence/test_pg_learnings.py`),
  `scripts/check-vulture-baseline.py`, quality-gate workflow and ledger.
- Planned edits: this report; ledger/source/tests only if a fresh gate establishes
  an actual in-scope repair. No test-count changes planned.

## Initial evidence and assumptions

No `check-*.log` files were present in the supplied current job-directory listing.
The prior result reports missing exact-RC deployment evidence and independent
replica rate allowances; these are claims to revalidate, not accepted proof.
Assumption: this is a writer CI-repair round, not authorization to select a release
candidate or introduce a new execution/authorization authority.

## Fresh initial results

- `uv sync --locked --extra dev`: PASS, 214 packages checked.
- Required exact vulture scan: PASS, 1323 findings / 1323 reviewed identities,
  zero unclassified. No ledger amendment is warranted by the fresh evidence.
- Historical check-3.log is a schema-fence assertion (24 actual DDL statements
  versus 21 expected), not a vulture failure. Fresh regression results below.
- `preflight_artifact_check()` still explicitly rejects the host-process driver
  as exact-RC evidence (`scripts/soak/run_soak.py:730`). The existing two-instance
  rate test exercises production middleware, not a mocked rate limiter.
- Logs so far: `/tmp/860-a8508a38-{sync,vulture}.log`.

## Focused validation checkpoint

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q -rs`: PASS, 37 passed / 6 skipped (requires migrated PostgreSQL DSN).
  The historical 21-versus-24 assertion no longer fails: the current test
  independently lists all three additional audit columns at lines 179–181.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  -x -q -rs`: PASS, 74 passed. This includes the production-middleware test
  showing `[200, 200, 429]` on each replica for the same identity, for both
  authenticated and unauthenticated traffic. That is not cluster non-bypass.
- Logs: `/tmp/860-a8508a38-{ruff,format,schema,soak-tests}.log`.
- CI workflow arguments checked in `ci.yml`, `quality.yml`, and
  `vulture-ratchet.yml`.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique identities, no duplicate evidence.
- `uv run python scripts/check-deployment-claims.py`: PASS (component existence
  only, not proof of a live production deployment).
- `git diff --check`: PASS. The first staged whitespace check later caught an
  extra blank line at EOF in this new report; removed before committing.
- Gate logs: `/tmp/860-a8508a38-{inventory,deployment}.log`.
- All validation commands used 1200-second timeouts; no full-tree pytest claim.

No implementation repair is supported by the reported CI failures: both the
schema regression and exact vulture gate pass freshly. No tests were added or
changed, hence no suite-inventory delta is required. The remaining acceptance
blocker is production soak evidence, not a scanner identity or a test count.

## Architecture reconciliation

Read `AGENTS.md`, `docs/README.md`, accepted ADR-085, ADR-081626-f383,
and ADR-082526-b36a, the load profile, adjacent regression tests and the
reachable production middleware. Preserve `Goal -> Graph -> Run -> NodeRun ->
Attempt`: the canonical Run store owns fences and the executor owns renewal.
The later lease ADR adds reclaim obligations; the earlier boundary cannot waive
recovery acceptance. Admission uniqueness does not prove physical-effect uniqueness.

ADR-085 requires per-principal rate identity. Production installs the middleware
at `packages/maistro-server/src/maistro_server/main.py:648`; its constructor at
`api/rate_limit.py:93` creates a process-local limiter. That documented scope
is weaker than #860's replica-selection non-bypass requirement. The fresh test
at `tests/test_soak_promotion_gates.py:439` confirms independent allowances;
it does not authorize inventing another auth path or treating that gap as closed.

## Acceptance audit

The frozen issue body supplies these ten criteria. Neither historical PR status
nor passing deterministic tests is exact-RC production acceptance evidence.

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:152` lists missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. `run_soak.py:1381` executes a narrower mix. No selected-RC applicability decision was supplied in the assignment. |
| At least two deployed application replicas | **UNVERIFIED**. Two-ASGI-instance and boot-contract tests passed, not a live pair of promoted images. No deployed production load ran this round. |
| Sustained saturation, queues, reclaim, retry/backoff, leaks and restart | **UNVERIFIED**. Sampler/admission regressions passed; these short tests do not observe sustained application resource or lease behavior. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | **UNVERIFIED**. `run_soak.py:1044` cancels the schedule probe Run without execution. Admission regression tests do not supply a physical-effect oracle. |
| Rate/security/degraded non-bypass | **UNVERIFIED as a whole; independent replica budgets observed**. The production middleware test freshly demonstrates replica selection increases available requests for the same identity. Backpressure and direct-path probe tests do not prove cluster-wide enforcement. |
| Full telemetry with explicit thresholds | **UNVERIFIED**. Profile thresholds and sampler tests exist; `run_soak.py:1410` samples driver-loop lag, not application-loop lag. No fresh complete production time series was judged against thresholds. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Fail-closed and boot-cleanup tests passed; no physical active-work restart experiment executed. |
| Long unchanged exact-RC artifact/configuration soak | **BLOCKED / UNVERIFIED**. No designated immutable RC/configuration in the assignment. `run_soak.py:730` rejects host-process preflight as exact-RC evidence. Synthetic long-duration test inputs are not four hours of traffic. |
| Findings filed/reclassified before promotion | Local dispositions recorded: historical schema failure does not reproduce; vulture matches; production evidence/rate-scope gaps remain. External filing/reclassification **UNVERIFIED**; GitHub mutations are prohibited. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED**. This report and local command logs describe validation of the starting source head, not a hash-bound RC production soak bundle. |

## Handoff

**BLOCKED.** Changed file: this report only. No production, test, inventory,
ledger, grant or runtime-configuration changes. No new soak was claimed and
no Docker availability limitation was assumed. The inherited branch is preserved;
this handoff is not integration approval.

Required next inputs/work: designate the immutable RC and supported deployment
configuration, settle the replica-budget contract, complete the representative
workload and physical-effect/recovery/application-telemetry oracles, then execute
at least 14400 seconds against the unchanged RC and publish the hash-bound bundle.
Do not retry the stale DDL assertion or amend a matching ledger as a substitute.

Checkpoint: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 unresolved validation commands; 111 tests passed / 6 database-dependent tests skipped.
One report-only staged whitespace failure was corrected before commit.
One initial candidate test path was not found and skipped as recorded above.
The local report commit completes this bounded writer handoff, not issue #860.
