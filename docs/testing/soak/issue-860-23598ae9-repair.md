# Issue #860 — repair job 23598ae9

## Frozen scope and initial checkpoint

- Assignment: issue #860 only; branch `auto-860`, worktree `/home/dev/Git/wt/auto-860`.
- Verified initial HEAD: `95a08ff19fd0ea9e6a1fc1639090ca844956dd18`; worktree clean.
- Scope snapshot: existing `scripts/soak/run_soak.py`, `scripts/soak/nginx-soak.conf`, `docs/testing/soak/m3a-{load-profile,soak-evidence}.md`, committed soak JSON evidence, `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`, adjacent changed pg_learnings/task admission code and tests, relevant deployment/rate-limit/execution ADRs, and the explicitly authorized `quality/vulture-baseline.json` gate repair. This report is the only planned new file; change implementation/ledger only for reproduced defects.
- Initial job-directory listing contains no `check-*.log`; driver-check claims are unavailable, not assumed true.
- Ambiguity: prompt mixes verifier and writer instructions. Proceed as assigned repair writer, run validation, document remaining acceptance blockers, and commit locally.
- No new RC artifact/configuration identifier was supplied. Existing short-run evidence cannot establish the required >=4h exact-artifact soak. Do not invent promotion evidence or weaken gates.

## Validation and disposition

- Executed the exact requested vulture command: PASS, 1370 findings / 1370 reviewed identities, zero unclassified and zero never-allowlist findings; protected base `4e50b46153bd`. Output: job-directory `vulture-validation.log`. No unbanked identity exists to repair; no ledger amendment is justified.
- Read the supplied prior result: BLOCKED, not promotion proof. Current evidence prose already corrects the old shared-store H3 claim: process-local state and independent replica allowances are explicit. Do not re-fix an absent defect.
- Read repository instructions and ADR-081 (Proposed), accepted ADR-085, ADR-081426-1f7c, ADR-081626-f383, and ADR-083126-5e62. Reconciliation: preserve canonical Attempt authority/fencing; ADR-081626-f383 explicitly does not itself establish expiry takeover. Admission uniqueness cannot establish physical execution uniqueness. ADR-085 per-principal limiting is not evidence of a shared cluster allowance.
- No GitHub mutation is permitted; load findings can only be recorded locally for owner triage.

- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS, 2731 files already formatted. Outputs: `ruff-check-validation.log`, `ruff-format-validation.log` in the job directory.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **88 passed, 5 skipped** in 7.70 s. Output: `pytest-validation.log`. The five PostgreSQL cases at lines 766/877/896/906/917 require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL result is claimed.
- Executed tests cover the real task router backed by the canonical in-memory Run spine, production rate-limit middleware with canonical principal resolution, and a live uv child memory/descriptor sampler. They are meaningful seam regressions, not multi-replica production soak evidence. In particular, both replica-selection identity cases pass by observing `[200, 200, 429]` independently on each replica instance.
- Inspected production Compose: two application services, PostgreSQL primary/replica, Redis and shared file-store. Its images remain reference tags/build context, not a supplied immutable RC selection. Startup/config tests do not prove deployment execution.

- Executed `uv run python` historical-evidence audit: imported the current evaluator and loaded the four frozen JSON packs (`m3a-soak-evidence`, `m3a-repair-validation`, `m3a-round5-final`, `m3a-round6-shakedown`). All four fail both `sustain_duration` and `exact_rc_artifact`; assertions passed. Round 5/6 record 90.17/90.43 seconds versus 14400 required. Machine-readable audit with historical identities: job-directory `evidence-validation.json`. This audit is not a new soak.
- An attempted ADR filename ending `canonical-attempt-lease-heartbeat-and-reclaim.md` was not found; skipped. Resolved the actual filename before further reading: accepted ADR-082526-b36a (`a-lease-that-stops-being-renewed-is-reclaimed.md`) extends the earlier fence contract with renewal/reclaim, and ADR-082426-82c7 assigns schedule occurrence uniqueness to the canonical Run store. These mechanisms must be exercised under load, not replaced or waived. No new scheduler, execution, event or authorization authority is introduced.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-server/tests`: PASS, 485 collected, recorded inventory matches. Same command with `--suite packages/maistro-core/tests`: PASS, 12003 collected. Logs: `inventory-{server,core}-validation.log`. No tests added or changed; no inventory delta needed.

## Acceptance assessment

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | **PARTIAL / UNVERIFIED**. `m3a-load-profile.md` defines a profile but explicitly records missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workers. Inspected `run_soak.py:1268–1289`: one credential, health/task/metrics mix. Applicability must be settled against the selected RC. |
| At least two application replicas | **UNVERIFIED for RC execution**. Compose declares two services and boot/config tests pass. No production-topology replicas were started in this round; host-process history cannot prove the exact artifact. |
| Sustained saturation, queue growth, expiry/reclaim, retries, memory/descriptor/process leaks, restart | **UNVERIFIED**. Four historical packs were rejected by current duration/artifact checks. No new long-window observations exist from this round. |
| Exactly-once/fenced physical work and Goal reconciliation | **UNVERIFIED**. Admission-oracle regression tests pass, but the schedule probe at `run_soak.py:947–1073` races one admission then cancels its queued Run without execution. That does not measure physical Attempt duplication or sustained Goal reconciliation. |
| Rate limiting/security/degraded behavior, replica-selection non-bypass | **NOT MET**. Executed `test_replica_selection_has_an_independent_production_allowance` for both identity classes: another allowance on replica 2 after exhaustion on replica 1. `rate_limit.py:25–30` and the actual middleware constructor confirm local state. No new production-concurrency security/degraded observation; six-path rejection is not a cluster budget. |
| PostgreSQL/loop/worker/RSS/descriptors/queue/error telemetry with thresholds | **PARTIAL / UNVERIFIED**. H1–H6/S1–S5 and sampler regressions exist. Live-child sampler test passes, but driver-loop lag is not application-loop lag and no current long-window RC resource/error series was captured. PostgreSQL integration tests were skipped, not counted as DB proof. |
| Kill/restart with drain/fencing/recovery during active work | **UNVERIFIED**. Historical exit/rejoin and terminal-Run counters are not Attempt/fence-correlated physical recovery evidence. No current RC failure injection was executed. |
| Long-running exact RC artifact/configuration soak, rerun after changes | **NOT MET**. `run_soak.py:635–645` always rejects the host preflight artifact; the executed CLI regressions reject even four-hour synthetic preflight evidence. No immutable RC image/config was supplied and no >=14400s exact-artifact soak was run. |
| Findings filed/reclassified at earliest invariant | **PARTIAL / UNVERIFIED**. Existing F11/F12 records classify evidence-validity defects at M3-A. No new load finding generated, no external filing verified or performed; GitHub mutations prohibited. |
| Hash-bound machine/human RC evidence | **PARTIAL / UNVERIFIED**. Historical identities were loaded by the audit, but none identifies a qualifying current RC soak. This report and job logs are validation evidence only. |

## Handoff / residual risks

**BLOCKED** for issue #860; the explicit vulture CI gate is green. The earlier H3 prose defect is already repaired in the starting tree. No reproduced new source or ledger defect justifies a speculative patch. Only this report changes; source, configuration, historical evidence, tests, ledgers and grants remain untouched. Commit locally as a blocked handoff, not an implementation completion or integration approval.

Next owner action: select immutable RC image/config hashes and provider configuration; resolve the replica-selection acceptance mismatch through the canonical enforcement path; complete the representative production workloads and application-side telemetry; run >=14400s with active-work failure injection and Attempt/lease/fence correlation. Any code/runtime-config changes require a fresh qualifying soak. Seam-test success cannot waive these blockers.

All validation used foreground commands with 1000–1200-second timeouts. Driver `check-*.log` files were absent at the initial snapshot; only independently executed writer checks above are claimed. No push, PR, issue mutation, ref change, background job or destructive Git operation was performed.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "#860 RC artifact selection, replica-budget reconciliation, representative >=4h production soak"}`. The one issue remains blocked; the missing ADR pathname noted above was an inspection miss, not a failed product gate.
