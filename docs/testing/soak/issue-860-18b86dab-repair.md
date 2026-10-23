# Issue #860 — repair checkpoint (18b86dab)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `849bd0867fc50f59a0e1f5a154a8df43298034e1` (verified); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean; no incoming diff to salvage.
- Process only the supplied dispatch snapshot; no GitHub mutations or re-enumeration.
- Candidate edit surfaces: this report and `quality/vulture-baseline.json` only, if the mandated exact scan establishes retained/deleted identities. Inspect existing soak runner/tests and relevant governance without changing production behavior speculatively.
- Assumption: this is the explicitly authorized ledger CI-repair round, not authorization to invent an RC artifact or alter release acceptance. Current job directory contains no `check-*.log`; inspect the supplied prior failed log instead.

## Progress

Initial state verified. Prior result reports BLOCKED, not release evidence.

- Mandated exact vulture scan passed: 1323 reviewed identities / 1323 findings, zero unclassified and never-allowlist findings. No ledger amendment justified; no inferred scanner repairs.
- Supplied historical check-3.log fails the learning schema fence test (24 DDL statements versus 21). Reproduced the targeted suite at this HEAD: **102 passed, 6 skipped** (`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`). The current test independently enumerates all 24 DDL statements, including the three Gauntlet audit columns; historical failure no longer reproduces.
- Current job has no deterministic check logs to inspect.
- Read repository instructions, documentation authority hierarchy and accepted ADRs 081226-69ee, 081626-f383 and 082126-f69c. Canonical Goal -> Graph -> Run -> NodeRun -> Attempt remains unchanged. Lease-expiry takeover is explicitly outside the accepted fencing contract; do not invent reclaim authority in a soak harness.
- Production middleware exercised by the existing tests gives the same principal `[200, 200, 429]` independently on each instance (both authentication classes). This proves local enforcement, not replica-selection non-bypass.
- Runner review confirms `preflight_artifact_check()` always returns false and the schedule race cancels its admitted Run without executing physical work. No speculative production/test/ledger edit justified.

## Remaining executed validation

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3270 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites / 31128 unique identities; no duplicate evidence.
- `uv run pytest tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 9 passed.
- `uv run python` loaded the current soak evaluator and the existing `m3a-round30-shakedown.json`: asserted failed checks are exactly `sustain_duration` and `exact_rc_artifact`; passed. Historical duration is 420.08 seconds versus 14400 required. Asserted current preflight artifact check remains false. This evaluates historical evidence, **not a new soak**.
- Verified the supplied base resolves. No sync conflict exists, so no fetch/merge performed.
- No production or tests changed; no inventory delta needed. The exact CI vulture command matches `.github/workflows/vulture-ratchet.yml:82` and passes without ledger edits.

## Acceptance evidence

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Representative RC load profile | **UNVERIFIED.** `m3a-load-profile.md:152` documents missing concurrent users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background traffic. Existing profile is explicitly preflight-only. |
| 2 | At least two deployed application replicas | **UNVERIFIED for RC.** Boot tests pass; ASGI middleware instances and historical host-process evidence do not establish the promoted deployment. |
| 3 | Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED.** Evaluated historical 420.08-second run fails duration; sampler tests are not sustained-load observations. |
| 4 | No duplicate physical work; Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044` cancels admission-probe work without execution. Receipt deduplication is not physical Attempt uniqueness. |
| 5 | Security/rate/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; contrary budget evidence reproduced.** `tests/test_soak_promotion_gates.py:439` exercises real production middleware and independently exhausts the same identity on both replicas. Process-local policy at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` is not a cluster budget. |
| 6 | Complete telemetry and explicit thresholds | **UNVERIFIED.** Sampler regression passes, but driver SELECT 1 and loop lag do not measure application query/loop behavior; profile documents remaining worker/saturation/reclaim gaps. |
| 7 | Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Boot cleanup is tested; deployed active-work recovery was not exercised. |
| 8 | Long exact unchanged RC soak | **UNVERIFIED / BLOCKED.** Current runner rejects its topology (`scripts/soak/run_soak.py:730`); historical evidence fails artifact and duration checks. No exact-RC soak executed. |
| 9 | Findings filed/reclassified before promotion | Local limitations recorded; external milestone disposition **UNVERIFIED**. No GitHub mutations permitted or performed. |
| 10 | Machine/human evidence bound to exact RC hashes | **UNVERIFIED.** Historical preflight evidence cannot establish current immutable RC image/config identity. |

## Handoff

**BLOCKED**, not integration approval. Only this report changes. The assigned CI gate is already green and the historical schema failure no longer reproduces. There is no evidenced CI repair to apply; do not amend the ledger merely because amendment is permitted.

Next requires a designated immutable RC image/configuration, a production-topology runner with representative physical-work/Goal workloads and complete telemetry, resolution of replica-selection budget semantics, then active-work restart and at least four hours of unchanged exact-RC load. Repeating these same unit tests cannot supply those prerequisites.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC prerequisites}`. Preserve this local report in a commit; no push, issue closure, or GitHub mutation.
