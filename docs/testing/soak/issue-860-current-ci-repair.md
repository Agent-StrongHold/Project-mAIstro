# Issue #860 — current CI repair

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `68d30470d57a6e6a7ec94986e0be50f11cfc47e3`.
- Assigned base: `234a06c515d76aca7c6b5a9b7f12c80278a06d0d`.
- Starting working tree clean; no salvage needed.
- Process the explicit vulture exact-debt-ledger gate, then focused existing soak/admission/persistence tests and acceptance evidence. Candidate edits are this report, `quality/vulture-baseline.json` only for observed reviewed retained identities, and source/test/inventory files only if the gate demonstrates actual dead code requiring repair. No execution-authority redesign or production rate-limit redesign is in scope.
- Inspect existing `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, load profile/evidence docs, production rate middleware, adjacent persistence/task tests and relevant accepted ADRs.
- Job directory has no `check-*.log` files at initial inspection. Do not rely on historical green claims.
- Prior result reports BLOCKED; independently validate rather than infer completion.

## Assumption and stop condition

This is a writer CI-repair round, not authorization to claim a host-uvicorn preflight is an exact production RC soak. No immutable RC image/configuration is supplied in the assignment. If production evidence remains missing, record it as UNVERIFIED and hand off blocked rather than fabricate a four-hour soak or weaken gates.

## Results

The requested vulture command passed (exit 0): 1,402 findings, 1,402 reviewed identities, 0 unclassified, 0 never-allowlist. No unbanked identity was reported, so no source deletion or ledger amendment is justified. The historical shared-store limiter claim is already corrected at the assigned HEAD; no duplicate cosmetic repair is needed.

Focused validation passed: `uv run ruff check .`; `uv run ruff format --check .` (2,624 files); `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs` (80 passed, 5 skipped in 5.91s). The five skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation is claimed. The passing tests include both authenticated and unauthenticated production-middleware counterexamples: replica 2 admits two more requests after the same identity exhausts replica 1.

Architecture review: accepted ADR-081226-a66b retains canonical lifecycle ownership; ADR-081626-f383 plus ADR-082526-b36a require Attempt fencing and explicit lease renewal/reclaim. ADR-082426-82c7 proves occurrence admission identity, not physical side-effect uniqueness. ADR-085 requires principal-keyed rate limits but does not establish shared replica state. ADR-081 is Proposed, not an accepted waiver of production evidence. No competing authority is introduced, and no acceptance criterion is waived.

Imported the current driver using `uv run python` and ran `failed_promotion_checks` over the four frozen historical packs. Assertions that each fails `sustain_duration` and `exact_rc_artifact` passed:

| Evidence file under `evidence/` | Recorded sustain seconds | Failed gates |
|---|---:|---:|
| `m3a-soak-evidence.json` | absent | 7 |
| `m3a-repair-validation.json` | absent | 7 |
| `m3a-round5-final.json` | 90.17 | 3 |
| `m3a-round6-shakedown.json` | 90.43 | 2 |

This evaluates recorded evidence, not the truth of every historical passing flag. The current driver (`scripts/soak/run_soak.py:635`) explicitly rejects exact-RC equivalence. Production `maistro_server/main.py:478` installs the middleware whose constructor allocates a separate in-memory limiter (`api/rate_limit.py:72`). The reference Compose (`deploy/docker-compose.prod.yml:26-62`) declares two application replicas, but local builds and mutable dependency tags are not an identified immutable RC.

Additional gates passed (exit 0):

- `uv run python scripts/check-deployment-claims.py`
- `uv run python scripts/check-execution-lifecycles.py` (19 discovered/classified lifecycles)
- `uv run python scripts/check-merge-markers.py`
- `git diff --check`

## Acceptance disposition

| Criterion | Current evidence / disposition |
|---|---|
| Representative RC profile | PARTIAL: existing profile has request mix and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC applicability UNVERIFIED. |
| At least two application replicas | Reference Compose inspected; actual exact-RC replica deployment UNVERIFIED. ASGI instances do not count as deployed replicas. |
| Sustained saturation, queue growth, reclaim, retry, leaks | UNVERIFIED: no sustained run executed; all four historical packs rejected. Subprocess sampler regression is not long-window observation. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED: profile's schedule probe admits then cancels a queued Run; admission uniqueness does not prove physical Attempt or side-effect uniqueness. |
| Rate/security/degraded behavior and replica non-bypass | NOT MET for aggregate principal allowance: executed production middleware regression proves a second allowance on the second replica for both authenticated and pre-auth identities. Full security/degraded behavior under RC load UNVERIFIED. |
| Complete metrics with explicit thresholds | PARTIAL: process-group sampler regression passes; complete application event-loop latency, worker census and RC metrics/threshold validation UNVERIFIED. |
| Active-work kill/restart drain/fencing/recovery | UNVERIFIED: no replica restart executed this round; historical rejoin/terminal counts do not prove physical-work recovery. |
| Long-running exact-RC soak; rerun after runtime/config change | BLOCKED: no designated immutable RC/configuration; current runner is explicitly not a promotion runner. No four-hour exact-RC soak executed. |
| Findings filed/reclassified to earliest invariant | PARTIAL: existing F11/F12 records classify M3-A evidence defects. External filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence tied to exact hashes | PARTIAL: historical packs preserved and evaluated, but qualifying RC image/package/config hashes and soak evidence UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. The requested CI failure does not reproduce. The prior block is missing release evidence and an observed rate-limit contract mismatch, not a merge conflict or unbanked vulture debt. Changing the ledger or re-running a short host-process soak cannot resolve it.

Only this report changed. No new tests, no inventory delta, no source/runtime-config, ledger, grant or historical evidence edits. No GitHub mutations.

Next owner must designate immutable RC images and configuration, establish the applicable representative workload, resolve the replica aggregate-limit mismatch without a parallel authorization path, provide a production-topology runner with physical Attempt correlation and full application telemetry, then execute at least four hours on that unchanged artifact/configuration. Runtime/config changes invalidate the run.

Progress: checked 1 assigned issue; done 0 (acceptance blocked); skipped 0 issues; errors 0 executed checks; 5 PostgreSQL tests skipped. Local commit records this checkpoint; the issue remains unresolved.
