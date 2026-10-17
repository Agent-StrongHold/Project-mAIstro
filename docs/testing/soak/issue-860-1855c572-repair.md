# Issue #860 — repair checkpoint (1855c572)

## Frozen scope

- Issue #860 only; branch `auto-860`, clean starting HEAD
  `77cf9fe43059d03e3d6c1a6a9ceea6875aa8601a`.
- Assigned comparison base: `8fbbbfb91d78d30d756cf675b7b1a4c1ccff06e5`.
- Inputs: supplied dispatch-context.json, prior result d27f7605, and prior
  check-3.log from job 98a11313. No check-*.log files were present in the
  current job directory at initial inspection.
- Repair surfaces: actual identities reported by the mandated vulture command,
  `quality/vulture-baseline.json` only if justified, and this validation record.
  Existing soak implementation/tests and governing ADRs are read/validation
  scope. No unrelated base divergence will be rewritten.
- Assumption: this is a writer CI-repair round, not a verifier-only round.
  Passing local gates does not prove representative exact-RC soak acceptance.

## Progress

- Mandated vulture scan PASS: 1,326 reviewed identities / 1,326 findings,
  zero unclassified or never-allowlist findings. No ledger amendment justified.
  Gate resolved merge-base `e46ad6708fda`, distinct from supplied develop tip.
- Prior check-3.log is a schema-test failure (24 DDL statements versus 21),
  not a scanner failure. Reproduction on the assigned HEAD is next.
- Prior BLOCKED result describes missing exact-RC acceptance, not a merge
  conflict. No develop merge is indicated by that evidence.
- `uv sync --locked --extra dev`: PASS (256 resolved, 214 checked).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: PASS, 37 passed / 6 skipped. Prior DDL-count failure does not
  reproduce; PostgreSQL-dependent skips do not prove live database behavior.
- Read accepted ADRs 081426-1f7c, 081626-f383, 082526-b36a and
  073126-c4e1: physical identity is Attempt, canonical persistence owns fences,
  lease renewal/reclaim extends the initial lease contract, and release
  provenance cannot be replaced by a branch preflight. No authority changes.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: PASS,
  100 tests. Includes production middleware instances reproducing independent
  per-replica allowances for the same authenticated principal or client IP.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,195 files already formatted.
- `uv run python scripts/check-merge-markers.py`: PASS.

No remaining scanner/schema defect reproduced. No speculative production or
ledger changes will be made. Exact-RC prerequisites remain unresolved; inspected
current production paths confirm that host preflight cannot prove promotion.

- `uv run python scripts/check-suite-inventory.py --suite tests/`: PASS,
  5,116 collected/unique identities, no duplicate evidence. No test additions
  or removals this round; no inventory delta required.
- `uv run python -` imported the current soak driver and called
  `failed_promotion_checks` on preserved `m3a-round30-shakedown.json`:
  assertions PASS that `sustain_duration` and `exact_rc_artifact` fail.
  Historical duration is 420.08 seconds versus 14,400 required. Also asserted
  `preflight_artifact_check()['ok'] is False`. This is a fresh negative
  evaluation of historical evidence, not a newly executed soak.

## Acceptance audit

All ten issue criteria checked against the supplied issue body and current
code; local tests are not substituted for deployed load evidence.

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` documents missing users/Workspaces, Graph fan-out, successful tool/model, Canvas and Goal-worker workloads; `run_soak.py:1382–1395` confirms the narrower executed mix. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Boot-contract and ASGI tests passed, but no immutable RC topology was deployed this round. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Fresh duration evaluation rejects the historical 420.08-second run. Process-group sampler tests passed, not a four-hour saturation experiment. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044–1072` cancels the schedule-admission probe Run without executing it. Admission uniqueness is not physical Attempt uniqueness under the accepted runtime/fencing ADRs. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED as a whole; contrary evidence for a shared budget.** Executed `tests/test_soak_promotion_gates.py:439–493`: same principal/IP gets `[200, 200, 429]` from each independent production middleware instance. `api/rate_limit.py:32–37` documents process-local enforcement. Resolve the deployment contract rather than silently introducing another authorization path. |
| Complete telemetry with thresholds | **UNVERIFIED.** `run_soak.py:1420–1430` measures driver loop lag, not application loop lag. Profile records remaining worker/pool/reclaim and long-window gaps. |
| Active-work kill/restart and drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1436–1489` records process exit/rejoin and HTTP counters, without an active-Attempt physical-work oracle. No restart experiment executed this round. |
| Long soak of exact RC/configuration | **BLOCKED / UNVERIFIED.** Current preflight explicitly fails the artifact gate (`run_soak.py:730–741`); evaluated historical evidence also fails duration. The dispatch supplies a branch HEAD but no selected immutable promoted image/runtime configuration. |
| Findings reclassified to earliest broken invariant | **UNVERIFIED completeness.** Historical profile records findings, but this round establishes neither complete classification nor resolution of every load finding. No GitHub mutation performed. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED for candidate.** Preserved historical artifacts remain unchanged; this report records local validation only. No new candidate image/config-bound soak evidence was produced. |

## Handoff

**BLOCKED.** Only this report changed. No production code, tests, gates,
quality ledgers or historical evidence were modified. Validation used long
command timeouts (1,000–1,200 seconds). No destructive git operations,
background deployment, remote mutations or release actions occurred.

The requested vulture and stale schema failures do not reproduce. A cosmetic
ledger amendment would not repair actual debt. The previous blocker is not a
sync conflict: it requires a selected immutable RC/configuration, completion
of representative production-path workloads and active-work observation, and
an executed minimum four-hour soak with complete telemetry. The process-local
rate contract must also be reconciled before asserting replica non-bypass.
Repeating gate-only repair cannot supply those acceptance prerequisites.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC acceptance prerequisites}. Local commit checkpoints this
validation; it is not issue completion or integration approval.
