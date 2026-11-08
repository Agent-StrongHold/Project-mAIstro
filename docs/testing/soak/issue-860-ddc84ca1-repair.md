# Issue #860 — bounded repair ddc84ca1

## Frozen scope

- Assigned issue only: #860; branch `auto-860`.
- Starting HEAD: `05b05479530ab535781938337f63bd5505a548f6` (resolved; clean).
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved).
- Evidence snapshot: supplied `dispatch-context.json`, prior job
  `1955a535b74249cf92639cd3a63b0aa3/result.json`, and reported failed
  `98a11313167b41a98a420abfda80c292/check-3.log`. No GitHub refresh/mutation.
- Repair candidates frozen to `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  adjacent `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` only for identities actually reported by the
  prescribed scanner, and this report (inventory note if tests change).
- Acceptance inspection: existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  production rate middleware and deployment wiring, relevant ADRs/quality docs.

## Initial evidence and assumptions

No current-job `check-*.log` files were supplied. The explicit prior log reports
24 DDL calls versus 21 expected in the schema-fence test; this will be rerun,
not assumed current. Prior result says BLOCKED, including missing exact-RC
identity and replica-local rate allowances. This is not a develop sync conflict;
no merge is requested by the conditional sync instruction. A large inherited
branch diff is preserved, not rewritten or represented as this repair's work.

## Reproduced results

- Exact prescribed Vulture invocation passed: 1323 findings, 1323 reviewed
  identities, zero unclassified and zero never-allowlist. Log:
  `/tmp/860-ddc84ca1-vulture.log`. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q` passed: **37 passed, 6 skipped**. Log:
  `/tmp/860-ddc84ca1-schema.log`. Both commands had 1200-second timeouts.
- The historical schema failure does not reproduce: the current independent
  expected-DDL list already contains the three validation audit columns at
  `test_pg_learnings.py:179-181`, matching production `_EPISTEMIC_COLUMNS`.
  Do not remove assertions or manufacture a code repair for the stale log.

## Focused validation

All validation commands use 1200-second timeouts.

| Command | Fresh outcome |
| --- | --- |
| `uv run ruff check .` | PASS (`/tmp/860-ddc84ca1-ruff.log`) |
| `uv run ruff format --check .` | PASS, 3270 files (`/tmp/860-ddc84ca1-format.log`) |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 74 passed (`/tmp/860-ddc84ca1-soak-tests.log`) |

Combined focused pytest: **111 passed, 6 skipped**. The persistence fixture
requires `MAISTRO_TEST_PG_DSN`; these six database tests are not claimed proven.
No tests were added/changed, hence no inventory delta is required.

## Architecture reconciliation

Read repository AGENTS.md, docs/README.md, quality-gates.md, accepted ADR-085,
ADR-081626-f383 and ADR-082526-b36a. Keep the canonical
Goal -> Graph -> Run -> NodeRun -> Attempt execution spine and its Run-store
lease authority. The later lease ADR requires renewal/reclaim; the earlier
ADR's deferred takeover boundary is not a waiver of recovery acceptance.
ADR-085 requires principal-keyed limits. Process-local limits documented by
#842 do not prove #860's stronger replica-selection non-bypass criterion.
This unresolved scope mismatch requires disposition, not another authorization
path or a weakened soak gate.

## Acceptance matrix

| #860 acceptance | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. Inspected `m3a-load-profile.md:152` and driver mix at `scripts/soak/run_soak.py:1381`: one credential, health/task/receipt/metrics traffic; no population of Workspaces, Graph fan-out, successful tool/model, Design/Canvas or Goal/background workload. No RC-specific exclusions established. |
| At least two deployed replicas | **UNVERIFIED**. Boot-contract tests pass and `deploy/docker-compose.prod.yml:27,77` declares two application services, but no designated RC deployment was executed. Middleware instances are not deployed replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retries and leaks | **UNVERIFIED**. Executed real child-process RSS/descriptor sampler regression and incomplete-sample tests; these do not establish long-running saturation/recovery behavior. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED**. Admission receipt tests pass; `run_soak.py:1044` explicitly cancels the schedule-probe Run without execution. Admission uniqueness does not prove physical-effect uniqueness. |
| Rate/security/degraded behavior non-bypass under replica selection | **Contrary local production-middleware evidence reproduced; deployment acceptance UNVERIFIED**. `tests/test_soak_promotion_gates.py:439` tests authenticated and unauthenticated identities receiving `[200, 200, 429]` on each independent replica, even after replica 1 exhausts its allowance. Production installs the middleware at `main.py:648`; `api/rate_limit.py:93` constructs `InMemoryRateLimiter`. No aggregate non-bypass proof. |
| Complete telemetry with explicit thresholds | **UNVERIFIED**. Profile lists thresholds; driver sampler at `run_soak.py:1410` measures driver loop lag, not application loop lag. No complete fresh production pool/query/lock/worker/queue/error telemetry or threshold adjudication executed. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED**. Executed boot cleanup and fail-closed gate tests, not an active-work recovery experiment on production replicas. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**. No designated immutable RC image/configuration supplied. Compose declares itself a reference requiring digest pinning (`deploy/docker-compose.prod.yml:11`). Executed synthetic four-hour CLI tests prove `run_soak.py:730` rejects host preflight as RC evidence; they are not four hours of traffic. |
| Findings filed/reclassified before promotion | Local disposition: historical schema failure does not reproduce, Vulture debt matches ledger, rate-budget mismatch and release evidence gaps remain. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED**. This is a validation report, not a hash-bound RC soak bundle. No fresh production soak evidence was generated. |

## Final checkpoint

- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique test identities, zero duplicate evidence.
  Log: `/tmp/860-ddc84ca1-inventory.log`.
- `uv run python scripts/check-deployment-claims.py`: PASS; component existence
  only, not deployment proof. Log: `/tmp/860-ddc84ca1-deployment.log`.
- `git diff --check`: PASS. CI gate invocations were inspected in
  `.github/workflows/{quality,vulture-ratchet,ci}.yml`.

**BLOCKED** on issue acceptance, not on the historical schema or Vulture gate.
Only this report changed this round; no production/test/ledger changes were
justified by the supplied failure and fresh checks. No existing work discarded,
no GitHub mutation, no new execution or authorization authority.

Next: release owner must designate an immutable RC/configuration; resolve the
replica-budget criterion mismatch, complete representative workload and
physical-effect/recovery/application-telemetry oracles, then run the unchanged
production artifact for the profile's minimum 14400 seconds. Docker is not
claimed unavailable; a short host preflight cannot replace these missing inputs
and experiments. The broad inherited branch diff is not certified by this review.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 fresh validation commands; six database-dependent tests skipped.
This report is the locally committed writer handoff, not promotion approval.
