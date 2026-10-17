# Issue #860 — repair validation (73e72f1e)

## Frozen scope

- Assigned item: #860 only; writer in `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, initial clean HEAD `57f7909f510965af3e28a37f08216086e1dbd43e`.
- Provided base `a2b95053a241246e444d7891951c63f7f2771fe4` resolves. The
  historical branch/base diff includes unrelated work; do not modify it.
- Review inputs: `AGENTS.md`, `CLAUDE.md`, relevant execution, rate-limit,
  deployment and evidence ADRs; `scripts/soak/run_soak.py`,
  `scripts/soak/nginx-soak.conf`, `deploy/nginx.conf`,
  `docs/testing/soak/m3a-load-profile.md`, `m3a-soak-evidence.md`, the four
  existing evidence JSON packs, `tests/test_soak_promotion_gates.py`,
  `tests/test_prod_stack_boot_contract.py`, production rate-limit/task code,
  and adjacent backpressure/schema-fence tests.
- Planned edit scope: this report; only an evidenced defect in the above
  scope would justify runtime/test edits and an inventory note. The explicit
  CI-repair exception permits `quality/vulture-baseline.json` changes only
  if the required gate demonstrates an identity needing review.
- Snapshot of driver logs: no `check-*.log` files were present in the assigned
  job directory at start; no driver checks are credited.
- Prior result read from job `23598ae926f748f8a612c628203d706a`: BLOCKED.
  Its claims will not substitute for fresh validation.

## Initial executed result

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
passed: 1,370 reviewed identities / 1,370 findings, zero unclassified or
never-allowlist findings. No ledger amendment or dead-code deletion is justified.

## Validation checkpoint

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2,731 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  **88 passed, 5 skipped** in 11.02 seconds. The five real-PostgreSQL tests
  require `MAISTRO_TEST_PG_DSN`; these skips are not database proof.
- `DOCKER_HOST=unix:///var/run/docker.sock docker version --format '{{.Server.Version}}'`:
  server 29.7.2 responds. Docker unavailability is **not** a blocker.
- Read accepted ADR-085, ADR-081426-1f7c, ADR-082526-b36a,
  ADR-082426-82c7 and ADR-083126-5e62, plus proposed ADR-081. Reconciliation:
  physical execution identity remains the canonical Attempt; occurrence
  admission uniqueness does not establish physical-work uniqueness. Lease
  heartbeat/reclaim must be observed through canonical execution, not a new
  scheduler. Per-principal limiting does not itself establish a shared
  cross-replica allowance.
- The old false shared-store H3 claim is already corrected in the initial
  tree (`m3a-soak-evidence.md:171`). Executed regression
  `test_replica_selection_has_an_independent_production_allowance` proves
  both identity classes receive `[200, 200, 429]` on each independent real
  middleware instance. Local limiter correctness is not #860 non-bypass.
- Inspected the complete host-process driver: `preflight_artifact_check`
  always returns false; the schedule probe cancels its queued Run without
  execution; sustained traffic uses one credential and no Graph fan-out,
  Canvas/Design or Goal reconciliation workload. No speculative source
  patch can turn this into RC promotion evidence.

## Final evidence audit

Executed a foreground `uv run python -` audit importing the current
`failed_promotion_checks` evaluator and reading exactly these four frozen packs.
Assertions required both `sustain_duration` and `exact_rc_artifact` to fail;
all assertions passed. The first two packs lack a top-level observed
`sustain_seconds`; the latter two record 90.17 and 90.43 seconds, respectively.
This is a fresh audit of historical evidence, **not** a new soak.

| Evidence JSON in `docs/testing/soak/evidence/` | SHA-256 of audited bytes |
| --- | --- |
| `m3a-soak-evidence.json` | `f9a3e0f594188f3008ccd614b92bc02dfcdd26925122b41a1c12a369848241be` |
| `m3a-repair-validation.json` | `076cd80bd6e295ce99bb33f6045426a80f9ba68294d4f9be86549d3fdfb0fec5` |
| `m3a-round5-final.json` | `47fcdd3ddaad286d6498027af7b64f91bb89f35aa0c85ccac35e9b824791a89f` |
| `m3a-round6-shakedown.json` | `19813c32aa5229489cc44e52d9bf91b83906f176085b370815d3539d95cd880b` |

Additional CI gates:

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests`:
  PASS, 485 tests match recorded inventory.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  PASS, 12,003 tests match recorded inventory.

No test was added or changed, so no inventory delta is needed. The executed
production-stack contract tests check real Settings/startup validation and
configuration, not live Compose behavior. The task-backpressure regression
uses the real task router and canonical in-memory Run store, proving 429 with
Retry-After and successful admission after a slot frees, not durable
cross-replica behavior. The sampler regression observes a live uv child, not
RC container resource health.

## Acceptance assessment

| #860 acceptance criterion | Executed evidence / remaining disposition |
| --- | --- |
| Representative concurrent users/Workspaces and workload profile | **PARTIAL; RC applicability UNVERIFIED.** Profile exists; production driver inspection confirms missing multiple principals/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker traffic. |
| At least two application replicas | **UNVERIFIED for RC execution.** Production Compose declares two services; configuration tests pass. No live RC topology was started in this round. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff and leak observations | **UNVERIFIED.** Current evaluator rejects all four historical packs; no new sustained workload executed. |
| Schedule/task/Run/Attempt uniqueness and Goal reconciliation without duplicated physical work | **UNVERIFIED.** Admission-oracle regressions pass, but `run_soak.py:947–1073` races admission and cancels the queued probe Run. Physical Attempt execution and sustained reconciliation are not observed. |
| Rate limiting/security/degraded concurrency behavior without replica-selection bypass | **NOT MET.** Both production-middleware identity regressions observe a second allowance on replica 2 after exhausting replica 1 (`tests/test_soak_promotion_gates.py:482–486`). Broader RC security/degraded behavior remains UNVERIFIED. |
| PostgreSQL, application-loop, worker/process, RSS, descriptor, queue and error telemetry with thresholds | **PARTIAL; RC observations UNVERIFIED.** Profile and live-child sampler tests exist; driver loop lag is not application loop lag. Five PostgreSQL tests skipped; no current database/load measurements credited. |
| Active-work replica kill/restart with drain/fencing/recovery | **UNVERIFIED.** Historical process rejoin/terminal counts cannot establish physical Attempt recovery; no current active-work fault injection executed. |
| At least four hours on exact RC artifact/config, rerun after changes | **NOT MET.** `run_soak.py:635–645` explicitly rejects host preflight; audited round 6 is 90.43s versus 14400s. No immutable RC selection was provided and no exact-artifact soak was executed. Docker is available; absence of qualifying evidence is not attributed to Docker failure. |
| Findings filed/reclassified to earliest milestone invariant | **PARTIAL; external filing UNVERIFIED.** Existing F11/F12 records classify evidence-validity failures at M3-A. No new load finding or external mutation in this round; GitHub filing is prohibited. |
| Machine/human soak evidence bound to exact image/package/commit/config hashes | **PARTIAL; qualifying RC evidence UNVERIFIED.** Historical JSON packs and human narrative exist and were audited, but all fail duration/artifact requirements. Their hashes above identify only the historical packs. |

## Handoff

**BLOCKED** for #860; the requested Vulture CI gate passes without amendment.
No new source/ledger defect was reproduced that justifies a speculative repair.
The prior block is unresolved: a corrected narrative or passing seam tests do
not complete a representative exact-RC soak. The only changed file in this
round is this report. Source, runtime configuration, historical evidence,
tests, ledgers and grants remain untouched.

Next owner actions: select immutable RC image/configuration and real provider
settings; resolve the replica-selection budget mismatch through the canonical
enforcement path; complete representative production workloads and
application-side telemetry; execute >=14400 seconds with active-work failure
injection and Attempt/lease/fence correlation. Any code/runtime-config change
requires a new qualifying soak. Do not rerun the host emulator for four hours
and call it production evidence.

All checks ran in the foreground with 600–1200-second timeouts. No push, PR,
issue mutation, background command, destructive Git operation or external
worktree edit was performed. Commit this report locally as a blocked handoff,
not integration approval.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 immutable RC selection, replica-budget reconciliation, representative >=4h production soak"}`.
