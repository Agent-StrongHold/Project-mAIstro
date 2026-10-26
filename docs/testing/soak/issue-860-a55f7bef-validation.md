# Issue #860 — bounded repair validation

## Frozen scope

- Job: `a55f7beff0cc4596b235d0739c84d76f`; writer lane `auto-860`.
- Starting HEAD: `8eafd9e03dd6e5efed9f9530666b84419d97b171`; supplied base: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Initial worktree clean; no incoming edits to salvage.
- Process only #860 and the supplied dispatch snapshot, not fresh GitHub lists.
- Inspect existing soak harness/profile/round109 evidence and adjacent tests,
  `pg_learnings` schema fence, task backpressure, relevant ADRs and CI gates.
- Planned edit: this validation/handoff record; production/test/ledger repair
  only if current executed checks identify an actual defect in this scope.
- No `check-*.log` files were present in the supplied job directory at start.
  The explicitly supplied previous `98a11313.../check-3.log` reports a schema
  fence assertion mismatch (24 observed statements versus 21 expected).
- Ambiguity: prior attempts label the missing RC soak an authorization block.
  This round will establish what the local evidence proves, without assuming
  authority to designate an RC or treating short shakedowns as a four-hour soak.

## Results

Executed so far (all exit 0): exact CI vulture command: 1322 reviewed
identities / 1322 findings, no unbanked identities; no ledger amendment warranted.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
37 passed, 6 skipped. The old 24-versus-21 mismatch does not reproduce: the
current independent expected DDL list includes all three Gauntlet columns.
`uv run ruff check .`: passed; `uv run ruff format --check .`: 3301 unchanged.
`uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -x -q`:
88 passed. `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
1 passed. `uv run python scripts/check-suite-inventory.py`: all 17 suites match,
31327 unique identities. No tests added; no inventory delta needed.

The raw round109 JSON reports 420.05 seconds, not 14400, and
`exact_rc_artifact.ok=false`. The profile explicitly lists missing representative
workloads, application loop metrics and physical-work recovery proof. Prior
summaries marking those whole criteria MET overstate this evidence; the final
assessment below will distinguish narrow admission/preflight proof from full
acceptance. No release/promotion approval is implied.

Additional executed checks (all exit 0):

- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  26 passed.
- `uv run pytest packages/maistro-core/tests/runs/test_spine_conformance.py -k occurrence_claim -x -q`:
  2 passed, 1 skipped, 398 deselected; skipped PostgreSQL coverage is not proof.
- `uv run pytest packages/maistro-core/tests/scheduling/test_admission.py::TestRecoverySeesTheRunStoreBeforeThePolicy::test_two_tickers_consuming_one_occurrence_count_it_once -x -q`:
  1 passed.
- `uv run python` imported the actual soak module and evaluated the raw
  round109 JSON: `failed_promotion_checks` returned exactly
  `['sustain_duration', 'exact_rc_artifact']`. This checks the evaluator,
  not a new live soak.
- The evidence's commit `5a59c724a20ef1241d57c048df90758f2c2e1e25` resolved;
  `git diff --exit-code <that-commit> HEAD -- packages/ scripts/soak/ deploy/`
  returned 0. Both source and rendered nginx SHA-256 values match the JSON.
  This limited source binding does not establish production image equivalence.

## Architecture reconciliation

Read accepted ADR-081226-a66b (one Run/NodeRun/Attempt lifecycle),
ADR-081626-f383 (durable Attempt fences), ADR-082426-82c7 (occurrence claims)
and ADR-085 (principal rate limiting). Also read ADR-081, which is **Proposed**,
not authority to waive an acceptance requirement. The deployed reference
Compose file declares two application services, PostgreSQL primary/replica,
Redis, shared files and a reachable model gateway. The host-process harness
is not that topology. No competing execution, event or authorization authority
has been introduced.

An occurrence claim demonstrates Run admission uniqueness, not absence of
repeated physical effects. Likewise, observing a process exit and zero
nonterminal Runs does not establish lease reclaim/stale-writer rejection.
ADR-085 does not turn process-local budgets into cluster-wide enforcement:
`maistro_server/api/rate_limit.py:32-37` explicitly documents N-times aggregate
allowance. That limitation remains an acceptance gap, not a waiver.

## Acceptance assessment (all ten criteria)

| # | Assessment against inspected production behavior and executed checks |
| --- | --- |
| 1 | **PARTIAL**: profile exists, but its remaining-gaps section explicitly lacks multiple users/Workspaces, fan-out, successful model/tool work, Design/Canvas and sustained reconciliation. RC applicability is UNVERIFIED. |
| 2 | **Historical preflight evidence only**: round109 JSON contains two directly probed replicas and per-replica measurements. Exact production-topology execution is UNVERIFIED this round. |
| 3 | **UNMET**: 420.05 seconds is below the profile's 14400 minimum. Pool saturation, lease expiry/reclaim and long-window leak behavior remain UNVERIFIED. |
| 4 | **PARTIAL**: executed occurrence/admission tests pass; raw JSON records one Run for twelve task submissions and one schedule occurrence. Physical Attempt effects and enabled Goal reconciliation across replicas remain UNVERIFIED. |
| 5 | **PARTIAL**: 26 middleware tests pass; historical six-path probes show 429s. Replica-independent allowance is not proven and conflicts with the documented process-local N-times budget. |
| 6 | **PARTIAL**: raw JSON records latency, RSS/FD and hard-check results; profile distinguishes driver-loop lag from application-loop latency. Application-loop health and complete required production metrics/thresholds remain UNVERIFIED. |
| 7 | **PARTIAL**: historical SIGTERM exit/rejoin, zero drain errors and zero nonterminal Runs are recorded. No new kill/restart was run; physical-work recovery/fencing remains UNVERIFIED. |
| 8 | **UNMET**: actual evaluator rejects both duration and exact artifact. `preflight_artifact_check()` always reports host-uvicorn, not a promoted Compose image. No immutable designated RC/configuration was supplied for a new production soak. |
| 9 | **PARTIAL**: existing `m3a-soak-evidence.md` records F1–F12 and invariant classifications; final external filing/disposition is UNVERIFIED. No GitHub mutations performed. |
| 10 | **PARTIAL**: machine/human preflight records exist; historical source and nginx hash bindings checked successfully. Exact promoted application image/configuration evidence remains UNVERIFIED. |

## Disposition and handoff

**BLOCKED**, not merge-ready. No current scanner debt or reproduced test defect
warrants a code/ledger edit. This round changes only this handoff and corrects
acceptance overclaims; it does not complete the requested soak. Existing code,
tests, evidence and gates are preserved. No test inventory change occurred.

Next prerequisite: release owner supplies the immutable RC image/configuration
and production-profile workload scope. The follow-on must run that topology for
at least four hours, instrument missing production metrics and physical-effect
fencing/recovery, and resolve the replica-selection rate-limit gap (or obtain
an explicit governed scope decision, not silently reinterpret acceptance).
Merely running the existing emulator longer cannot satisfy the artifact gate.
Do not repeat this bounded shakedown or stale schema-test repair as a substitute.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC production soak and remaining acceptance gaps"}`.
The single assigned issue remains blocked; local validation/handoff is complete.

## Revalidation — job b02de7b02d314455957a06bbff5ffffe

Frozen scope: #860 only, clean `auto-860` at
`3944cacdb52635ef7ccd5cb702129bf9d45fca3e`, supplied develop base unchanged.
This section updates the existing handoff instead of creating another parallel
repair report. Current job supplied no `check-*.log`; the named prior
`98a11313.../check-3.log` is the 24-versus-21 schema assertion failure.

Fresh executions (not inherited verification claims):

- Exact requested vulture scan: exit 0, 1322 findings / reviewed identities,
  zero unclassified. No retained unbanked identities exist to amend; changing
  `quality/vulture-baseline.json` would have no evidential basis.
- Schema regression file: 37 passed, 6 PostgreSQL tests skipped. The expected
  list already includes all three Gauntlet validation columns at lines 172–176;
  the supplied failure does not reproduce. Skips do not prove live DB fencing.
- `uv run ruff check .`: exit 0; `uv run ruff format --check .`: exit 0,
  3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -x -q`:
  88 passed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  27 passed.

Re-read accepted lifecycle, execution-fencing, occurrence-claim and rate-limit
ADRs, the actual soak evaluator, production Compose topology, middleware and
adjacent tests. The same architectural distinction holds: canonical Run
admission uniqueness is not physical Attempt effect uniqueness. The accepted
execution-fencing ADR explicitly leaves expiry takeover outside its current
contract; no new reclaim authority may be invented to satisfy this issue.
`RateLimitMiddleware` constructs a separate `InMemoryRateLimiter` per instance;
per-replica 429 responses alone cannot prove a replica-independent allowance.
No production code, gates, ledger or tests changed in this revalidation, so no
inventory delta is needed.

`uv run python scripts/check-suite-inventory.py`: exit 0, all 17 suites match,
31327 unique identities. An executed `uv run python` import of the actual soak
module evaluated `m3a-round109-shakedown.json`: 420.05 seconds versus 14400
minimum, failing exactly `sustain_duration` and `exact_rc_artifact`. This was
an evaluator check, not a new live soak. Full command output is retained in
`/home/dev/maistro/jobs/b02de7b02d314455957a06bbff5ffffe/worker-*.log`.

### Fresh acceptance assessment

| Criterion | Evidence and remaining limitation |
| --- | --- |
| 1 Representative profile | Inspected `m3a-load-profile.md`; concurrent users/Workspaces, fan-out, successful model/tool work and Design/Canvas coverage remain UNVERIFIED. |
| 2 Two replicas | Historical raw JSON has two direct-replica probes; no new production-topology execution, therefore UNVERIFIED for this RC. |
| 3 Sustained load | Executed evaluator rejects 420.05 seconds; long-window saturation/reclaim/leaks remain UNVERIFIED. |
| 4 Exactly-once physical work | Historical one-Run admission and cancelled occurrence probe do not establish physical effects or Goal reconciliation: UNVERIFIED. |
| 5 Security/degraded/rate behavior | 27 server tests pass; replica-independent allowance remains UNVERIFIED and middleware budgets are explicitly process-local. |
| 6 Required metrics/thresholds | Existing profile distinguishes driver-loop lag from application-loop latency; complete production instrumentation remains UNVERIFIED. |
| 7 Kill/restart during work | Historical SIGTERM/rejoin record inspected; no live kill/restart this round, physical fencing/recovery remains UNVERIFIED. |
| 8 Exact-RC long soak | UNMET: actual evaluator rejects duration and artifact. No immutable designated RC supplied in the lane assignment. |
| 9 Finding disposition | Existing evidence/handoff records retained; external filing and final reclassification remain UNVERIFIED. No remote mutations. |
| 10 Hash-bound publication | Historical JSON contains commit/config hashes, not exact promoted application image evidence; promotion-grade identity remains UNVERIFIED. |

Disposition remains **BLOCKED**, not a completed implementation or integration
approval. The supplied scanner/test repair request has no currently reproduced
failure. No cosmetic code or ledger change was made to manufacture a repair.
Next action is the production-artifact/workload decision and missing soak work
already listed above, not another run of the same short emulator. Progress:
`{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 exact-RC soak"}`.

