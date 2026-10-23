# Issue #860 — bounded repair validation (9c3ed1ba)

## Frozen scope

- Sole item: issue #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `f1fe47431cc2ff8a2d982c6239bf5fef2e72cb30` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Clean incoming worktree; no salvage patch necessary.
- Evidence snapshot: supplied `dispatch-context.json`, previous result
  `34d6dc7a63af4b11aa64f5defecf8041/result.json`, and cited prior
  `98a11313167b41a98a420abfda80c292/check-3.log`. No check logs were present in
  this job directory at initial inspection. No GitHub refresh/mutation.
- Processing scope: soak harness/profile/promotion checks and adjacent tests,
  relevant repository instructions/ADRs, exact vulture CI gate and its ledger
  only if fresh evidence requires repair. Output file: this report.
- Ambiguity: dispatch requests gate repair but previous result reports missing
  RC designation. Treat both as claims to validate, not permission to invent
  a release artifact or change production authority.

## Progress

Fresh requested vulture scan: PASS (1323 reviewed identities / 1323 findings,
zero unclassified or forbidden; automatic comparison base `4aa68edc0b6b`).
Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
-x -q`: 37 passed, 6 skipped. Both commands used 1200-second timeout.
The cited historical failure (24 schema statements versus 21 expected) does not
reproduce. No fresh evidence supports a schema or ledger repair. Logs:
`/tmp/860-9c3ed1ba-vulture.log`, `/tmp/860-9c3ed1ba-schema.log`.
Additional fresh validation (1200-second timeout):

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3270 files).
- `uv run pytest tests/test_soak_promotion_gates.py -x -q -rs`: 65 passed.
- `uv run python scripts/check-deployment-claims.py`: PASS; existence only,
  not a deployed concurrency proof.
- `uv run python scripts/check-suite-inventory.py`: PASS; 17 suites, 31128
  unique identities, no duplicate evidence. No tests added or changed; no
  inventory delta required.

Logs are `/tmp/860-9c3ed1ba-{ruff,format,soak-tests,deployment,inventory}.log`.
The production-middleware test reproduces independent allowances on both replica
instances for both authenticated and unauthenticated clients. This is a real
middleware seam, not a deployed RC traffic test. Production acceptance remains
blocked as detailed below.

## Architecture and reachable behavior

Read repository instructions, the documentation authority map and accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. The later lease ADR requires
renewal/expiry reclamation, not restart-implies-death. Admission uniqueness is
not physical-work uniqueness. No alternate scheduler, authority or authorization
path was added.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` holds the
  schema advisory lock within the DDL transaction. The ordered independent test
  expectation at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175`
  already includes the three validation-audit columns absent in the cited log.
- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` constructs an instance-local
  limiter. Executed `tests/test_soak_promotion_gates.py:439` observes
  `[200, 200, 429]` on each instance for the same identity. Per-principal keying
  does not establish a shared replica allowance. Existing #842 scope explicitly
  documents N-times aggregate limits; #860's stronger non-bypass criterion is
  not thereby waived. Reconcile through the existing enforcement owner, not a
  second auth path in the soak harness.
- `scripts/soak/run_soak.py:730` deliberately fails exact-RC certification for
  host-process topology. Extending duration cannot satisfy that artifact gate.
- `deploy/docker-compose.prod.yml:11` identifies a reference topology requiring
  pinned images; the assignment supplies source refs but no designated immutable
  RC/configuration. Building an arbitrary local image is not proof of what #89
  would promote.
- `docs/testing/soak/m3a-load-profile.md:151` identifies missing representative
  workloads and telemetry. Its schedule probe cancels an admitted queued Run
  without physical execution (lines 193–203); driver-loop measurements are not
  application-loop latency. Historical evidence was not recertified.

## Acceptance disposition

| Criterion | Executed evidence / remaining requirement |
| --- | --- |
| Representative RC profile | UNVERIFIED: current profile omits concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background reconciliation applicability. |
| At least two application replicas | UNVERIFIED for deployed RC: two middleware instances in tests do not prove two deployed immutable artifacts. |
| Sustained saturation, queue/reclaim/retry/leak/shutdown observations | UNVERIFIED: regression tests are not a long load time series. |
| No duplicated physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED: no production physical-work witness executed. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent local allowances reproduced by executed production-middleware tests; cluster non-bypass and broader deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED for RC: no new PG/application-loop/worker/RSS/descriptor/queue/error series. |
| Kill/restart during active work; drain/fencing/recovery | UNVERIFIED: no active-work recovery fault injection executed. |
| Long soak of exact promoted RC/configuration | BLOCKED / UNVERIFIED: no immutable RC/config designated; host preflight cannot certify it. |
| Findings filed/reclassified before promotion | Local correctness disposition recorded above; external filing/reclassification UNVERIFIED (GitHub mutations prohibited). |
| Machine/human evidence bound to artifact/config hashes | UNVERIFIED for RC: this source-bound validation report is not an RC evidence bundle. |

## Handoff

Only this report changes. No test-count changes, ledger changes, gate weakening,
production changes, discarded work, sync conflict, fetch/merge or GitHub mutation.
`git diff --check` passes; the supplied base resolves locally. The requested
vulture command matches `.github/workflows/vulture-ratchet.yml:82`; its automatic
comparison base differs from the supplied develop base and is reported above.

Verdict: BLOCKED, not integration approval. The cited deterministic failure is
resolved in the incoming tree, but the original production-soak prerequisites
remain missing. Do not repeat a repair against the same stale failure log.
Next input needed: designated immutable RC and runtime configuration, completed
representative production workload and telemetry/physical-work witnesses, and
resolution of the replica-budget claim. Then execute the long exact-RC soak and
publish hash-bound evidence. No short host-process soak was substituted.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
Local commit records this report; no other files are changed.
