# Issue #860 repair checkpoint — f5e2087a

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD `51f96c8e7c1f0d0f78448eb191963214cf32bbd4`; clean working tree.
- Supplied base `140e881808475a4dbec063d19740e1e50c340905` resolves locally.
- Evidence inputs: supplied dispatch-context.json and prior result 478f2ecb.
- No driver check-*.log files present at initial job-directory inspection.
- Files in repair scope: this report, `quality/vulture-baseline.json` only if
  the mandated scanner identifies reviewed retained debt, and an inventory note
  only if the reported root-suite count discrepancy has attributable evidence.
- Read-only acceptance surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, server rate limiter/task admission and
  adjacent tests, `docs/testing/soak/m3a-load-profile.md`, round30 evidence,
  suite-inventory checker/notes, relevant ADRs and quality-gate documentation.

Assumption: this is the writer CI-repair lane, not the read-only verifier lane.
No GitHub mutations, ref refreshes, deployment changes, or acceptance waivers.
Prior BLOCKED result is a claim to revalidate, not approval or current evidence.

## Progress

- Mandated vulture scan PASS: 1322 reviewed identities / 1322 findings,
  zero unclassified. No ledger amendment is justified.
- Root suite inventory failure reproduced: expected 5353, collected 5354;
  zero duplicate test identities. Provenance resolved: the supplied base's
  `1993-hive-permission-preset-inventory.md` (+1) is absent here, but its
  `test_hive_preset_tracks_the_executable_registry` node still collects and
  passes. The complete test module has identical Git blob
  `5a0f01f0b99306e80596dfbc7a05085005205f7a` at HEAD and the supplied base;
  it collects/passes ten cases, while `cutover-s1-9-warden-aggregate.md`
  accounts for the original nine. The only other matching note,
  `auto-390-develop-sync-union.md`, contributes zero.
- Reinstated the exact base note at its original path (not a second +1 note,
  which would double-count on a later develop merge). Its prose remains the
  historical base measurement, not this branch's current total. No tests,
  baseline, quality ledger, grants, or gate implementation were changed.
- After repair, root inventory PASS: expected/collected 5354, zero duplicate
  identities. This resolves the prior inventory blocker with named-node evidence.
- Read issue acceptance from frozen dispatch and current load profile: the
  runner explicitly remains non-RC preflight and omits representative workloads.
  No long-running production soak has been executed in this job.
- `uv run ruff check .` PASS; `uv run ruff format --check .` PASS (3306 files).
- Focused root soak/boot/gitleaks contract tests PASS (100 tests).
- Server rate-limit and task-concurrency-backpressure tests PASS (27 tests).

## Executed validation

All commands below ran locally using long timeouts; no prior pass was assumed.

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322/1322 identities; gate reports base `2f56be40ad24` |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3306 files |
| `uv run python scripts/check-suite-inventory.py --suite tests` | Before: FAIL 5353 expected / 5354 collected; after: PASS 5354/5354 |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q` | PASS, 100 tests |
| `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS, 27 tests |
| `uv run pytest tests/security/test_sentinel_permission_table_armed.py --collect-only -q` | 10 nodes including the named parity test |
| `uv run pytest tests/security/test_sentinel_permission_table_armed.py -x -q` | PASS, 10 tests |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence only, not load proof |
| `uv run python` loading current soak evaluator and round30 JSON | Assertions PASS: failed gates include `sustain_duration` and `exact_rc_artifact`; current preflight artifact check is false |
| `git diff --check` | PASS |

## Architecture reconciliation

Read accepted ADR-085, ADR-081426-1f7c, ADR-081626-f383 and
ADR-082526-547c. Request limits remain keyed through the canonical principal
resolver; the production middleware explicitly provides independent per-replica
budgets, not a shared budget. This is not proof of #860's stronger
replica-selection requirement. Physical execution authority remains the canonical
Attempt and Run-store lease/fence, not the load driver. The fencing ADR explicitly
does not define expiry takeover; a cancelled schedule-admission probe cannot
prove physical-work reclaim. No new scheduler, Goal store, authorization path or
execution authority was introduced. Inventory accounting uses the existing
per-change delta contract, with the original note identity preserved.

## Acceptance assessment

| #860 criterion | Executed evidence / remaining requirement |
|---|---|
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md:167–183` leaves concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas and reconciliation incomplete. |
| At least two production replicas | **UNVERIFIED**: ASGI production-middleware probes passed; no exact-RC deployment was exercised. |
| Sustained saturation, queue/reclaim/backoff and resource leak observations | **UNVERIFIED**: evaluated round30 evidence is 420.08 seconds, below the 14400-second profile minimum. |
| No duplicate physical work; schedules, Run/Attempt admission and Goal reconciliation | **UNVERIFIED**: profile lines 215–217 identify a cancelled single-occurrence admission probe, not execution or sustained reconciliation. |
| Effective security/degraded limits without replica-selection bypass | **NOT PROVEN**: executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities reproduces `[200,200,429]` independently on both middleware instances (`tests/test_soak_promotion_gates.py:479–527`). Production `rate_limit.py:32–37,93` documents/creates local allowances. |
| Required production telemetry and explicit thresholds | **UNVERIFIED**: documented driver-loop measurements are not application-loop latency; production saturation/worker/lease observations remain missing. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED**: unit/boot checks and process-rejoin evidence cannot prove no loss or duplicate physical work. |
| Long-running exact RC/configuration soak | **NOT MET** by evaluated evidence: current `scripts/soak/run_soak.py:744–755` intentionally rejects its host-process artifact; evaluated JSON fails both duration and artifact gates. |
| Findings filed/reclassified to earliest milestone | **UNVERIFIED** externally; local evidence recorded here, no GitHub mutation performed. |
| Machine/human evidence bound to promoted hashes | **UNVERIFIED**: historical preflight JSON and Markdown do not establish the promoted artifact/configuration for this HEAD. |

## Handoff

**BLOCKED for issue acceptance; inventory repair ready for review only.**
Changed files: the reinstated inventory note and this report. No test addition,
production change, history rewrite or quality-ledger amendment was needed.
The vulture defect does not reproduce; repeating that repair request cannot
supply missing production acceptance evidence.

Next: select immutable RC images/configuration, implement/use a production-path
workload covering the outstanding surfaces, resolve the replica-budget policy
mismatch through the existing security authority, and execute the required
four-hour soak with physical-work and telemetry evidence. Do not substitute a
longer host-process preflight or unit tests for that run. Preserve this note's
original filename on future merges to avoid counting the same parity test twice.

Progress: checked 1 assigned issue; done 0 acceptance-complete; skipped 0;
validation errors remaining 0 after the inventory repair. Production acceptance
blockers remain as listed above. Local commit is a handoff, not promotion approval.
