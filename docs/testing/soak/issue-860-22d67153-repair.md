# Issue #860 — bounded repair 22d67153

## Frozen scope

- One issue: #860; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified clean starting HEAD: `3c61a1d2abd3dfeb3ed3a8055cf548b54b2d1751`.
- Repair surfaces (only if reproduced): `quality/vulture-baseline.json`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`.
- Acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, existing soak profile/evidence,
  relevant ADRs and CI gate definitions. No other issue or PR processing.
- This report and, if test changes are required,
  `docs/testing/inventory-notes/m3a-860-22d67153-repair.md` are documentation surfaces.

## Initial evidence / assumptions

Current job contains no `check-*.log`. Supplied prior `check-3.log` reports
24 schema statements versus 21 expected in the advisory-lock test. Prior result
is BLOCKED on exact-RC deployment/load evidence. Neither claim is assumed current.
This is an explicit vulture CI-repair round: ledger changes are allowed only for
actual reviewed scanner identities. No authorization grants or gate weakening.
Missing exact-RC identity/configuration will be reported rather than invented.

## Reproduced results

- Exact vulture command passed: 1,323 findings, 1,323 reviewed identities,
  zero unclassified/never-allowlist findings. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 PostgreSQL-dependent tests skipped. The reported 24-versus-21
  failure is already repaired: the independent expected DDL list includes all
  three Gauntlet audit columns. No schema/test change is justified.
- Discovery of `scripts/soak/README*`, `docs/testing/soak/README*`, and
  `docs/adr/*145*`: not found; skipped. These are not validation failures.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS, 65 tests,
  including the real production middleware's independent-replica allowances
  and a real child-process RSS/descriptor sampler test. These are not RC load.

Read accepted ADR-081226-69ee, ADR-081626-f383, ADR-082126-f69c and
ADR-082526-b36a. Reconciliation: the later lease contract adds explicit fenced
renewal/reclamation to the earlier lease boundary; schedules admit canonical
Runs, not another runtime. Goal -> Graph -> Run -> NodeRun -> Attempt remains
unchanged. No competing scheduler, authority, store, or authorization path added.

- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31,128 unique identities, no duplicate evidence. No tests added or changed;
  no inventory delta required.
- `uv run python` imported the current driver and evaluated
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`: historical sustain
  420.08 seconds versus 14,400 required; asserted failed checks exactly
  `sustain_duration` and `exact_rc_artifact`. Also executed
  `preflight_artifact_check()` and asserted `ok is False`.
- Command output retained at `/tmp/860-22d67153-{vulture,pg-tests,ruff,format,soak-tests,inventory,artifact}.log`.
  Validation timeouts were 1,200 seconds. The default vulture scan reports
  provenance base `4aa68edc0b6b`; no ref or provenance configuration changed.

## All ten acceptance criteria

| Criterion | Current evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** `m3a-load-profile.md:152` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. No selected RC configuration justifies exclusions. |
| At least two deployed application replicas | **UNVERIFIED for RC.** Tests execute two production middleware instances, not two deployed RC application replicas. No new deployment executed. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | **UNVERIFIED.** Re-evaluated historical 420.08-second window fails duration. Real process sampler regression is not sustained deployed-load evidence. |
| No duplicate physical work; Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` explicitly cancels the admission probe Run without executing it. Admission identity is not physical Attempt uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall, with contrary rate-budget evidence.** Executed `tests/test_soak_promotion_gates.py:439`: the same authenticated or pre-auth identity gets `[200, 200, 429]` independently on each production limiter. `rate_limit.py:32` documents process-local N-times aggregate allowance. Resolving the acceptance/policy mismatch is not authorized by a CI ledger repair. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Profile defines thresholds but acknowledges driver loop lag is not application loop latency and SELECT 1 wire latency is not application query latency. No new RC telemetry collected. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** Fail-closed drain and cleanup unit tests pass; no deployed active-work kill/recovery executed. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED.** Executed artifact check at `scripts/soak/run_soak.py:730` returns false; historical evidence fails duration and artifact gates. Assignment supplies no immutable RC image/configuration to promote. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally.** Local gaps recorded here. No GitHub mutation permitted or performed. |
| Machine/human evidence tied to exact artifact/config hashes | **UNVERIFIED for RC.** Historical preflight evidence and this validation report are not an exact-RC promotion pack. |

## Disposition

**BLOCKED**, not merge-ready. The explicit vulture repair and historical schema
failure require no further code/ledger edit: both pass on the assigned HEAD.
Only this report changes. No grants, gates, inventory, runtime configuration,
or production behavior changed. No merge conflict exists; no fetch/merge needed.

Next: designate the immutable RC image and configuration; complete the
production-topology workload, telemetry and active-work fencing/recovery
coverage; reconcile replica-selection rate policy; then run at least four
hours on the unchanged RC and publish hash-bound evidence. Another identical
CI-repair dispatch cannot provide these missing prerequisites.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`.
`done` counts full issue acceptance, not passing validation commands. Residual
risk is unproven production behavior; six PostgreSQL-dependent persistence
tests were skipped. Local commit contains this handoff only.
